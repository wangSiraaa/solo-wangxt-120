"""定位引擎: 网格搜索 + 最小二乘精化, 输出残差、不确定度与几何覆盖诊断。

教学原则:
- 绝不只报一个"精确坐标": 同时给出 RMS 残差、逐台残差、68% 置信椭圆、
  方位角空隙与可定位性状态。
- 台站不足或几何覆盖太差时明确报告 UNLOCATABLE, 而不是硬凑一个解。
- P/S 残差分开统计, 速度模型版本与数据版本绑定到结果上。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .travel_time import (
    azimuth_deg,
    km_to_lonlat,
    lonlat_to_km,
    source_station_distance_km,
    travel_time_s,
)
from .velocity_model import ENGINE_VERSION, VelocityModel

MIN_STATIONS = 3            # 少于 3 个台站不可定位
MIN_PICKS = 3               # 少于 3 条到时不可定位
MAX_AZIMUTHAL_GAP_DEG = 180.0   # 方位角空隙超过该值视为几何覆盖不足
COND_WARN = 1.0e6           # 法方程条件数超过该值给出"约束很弱"警告
OUTLIER_MAD_K = 3.0         # 残差超过 K 倍稳健标准差标记为离群
OUTLIER_FLOOR_S = 0.5       # 离群判定的残差下限(秒), 避免噪声过小时误报


@dataclass
class Station:
    id: str
    name: str
    lat: float
    lon: float


@dataclass
class Pick:
    station_id: str
    phase: str            # "P" 或 "S", 严格区分
    time_s: float         # 相对于场景参考时刻的秒
    weight: float = 1.0


@dataclass
class PickResidual:
    station_id: str
    phase: str
    observed_s: float
    predicted_s: float
    residual_s: float
    is_outlier: bool


@dataclass
class LocationResult:
    status: str                     # OK / POORLY_CONSTRAINED / UNLOCATABLE
    status_reasons: list[str]
    lat: float | None
    lon: float | None
    depth_km: float                 # 固定深度, 非反演结果
    origin_time_s: float | None
    rms_residual_s: float | None
    residuals: list[PickResidual]
    azimuthal_gap_deg: float | None
    condition_number: float | None
    ellipse_68: dict | None         # 68% 置信椭圆 (半轴 km, 方位角)
    alternate_minimum: dict | None  # 网格搜索发现的镜像/多解极小 (共线台阵的典型陷阱)
    n_stations: int
    n_p_picks: int
    n_s_picks: int
    model_version: str
    engine_version: str
    data_version: str
    disclaimer: str = "教学演示结果, 基于简化均匀速度模型, 不构成真实地震预警。"


def _data_version(picks: list[Pick], stations: dict[str, Station], model: VelocityModel) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(model.version.encode())
    for sid in sorted(stations):
        s = stations[sid]
        h.update(f"{sid}:{s.lat:.6f}:{s.lon:.6f}".encode())
    for p in sorted(picks, key=lambda p: (p.station_id, p.phase, p.time_s)):
        h.update(f"{p.station_id}:{p.phase.upper()}:{p.time_s:.4f}:{p.weight:.3f}".encode())
    return h.hexdigest()[:12]


def _azimuthal_gap(azimuths: list[float]) -> float:
    if len(azimuths) < 2:
        return 360.0
    az = sorted(a % 360.0 for a in azimuths)
    gaps = [az[i + 1] - az[i] for i in range(len(az) - 1)]
    gaps.append(az[0] + 360.0 - az[-1])
    return max(gaps)


def _robust_outliers(residuals: np.ndarray, phases: list[str]) -> np.ndarray:
    """按震相分组做 MAD 离群检测; 组内样本太少时退化为全体一起算。"""
    flags = np.zeros(len(residuals), dtype=bool)
    phases_arr = np.array([p.upper() for p in phases])
    groups = [phases_arr == ph for ph in ("P", "S") if (phases_arr == ph).sum() >= 4]
    if not groups:
        groups = [np.ones(len(residuals), dtype=bool)]
    for mask in groups:
        r = residuals[mask]
        med = np.median(r)
        sigma = 1.4826 * np.median(np.abs(r - med))
        thresh = max(OUTLIER_MAD_K * sigma, OUTLIER_FLOOR_S)
        flags[mask] = np.abs(r - med) > thresh
    return flags


def locate(
    picks: list[Pick],
    stations: dict[str, Station],
    model: VelocityModel,
    data_version: str | None = None,
) -> LocationResult:
    """主入口。picks 中每条到时必须带 P 或 S 震相。"""
    dv = data_version or _data_version(picks, stations, model)
    base = dict(
        depth_km=model.fixed_depth_km,
        model_version=model.version,
        engine_version=ENGINE_VERSION,
        data_version=dv,
    )

    # --- 输入校验: 未知震相直接拒绝, 不允许混用速度 ---
    used: list[tuple[Pick, Station]] = []
    for p in picks:
        model.velocity_for_phase(p.phase)  # 非法震相在此抛错
        sta = stations.get(p.station_id)
        if sta is not None and p.weight > 0:
            used.append((p, sta))

    used_station_ids = {p.station_id for p, _ in used}
    n_p = sum(1 for p, _ in used if p.phase.upper() == "P")
    n_s = sum(1 for p, _ in used if p.phase.upper() == "S")

    def unlocatable(reasons: list[str]) -> LocationResult:
        return LocationResult(
            status="UNLOCATABLE", status_reasons=reasons,
            lat=None, lon=None, origin_time_s=None, rms_residual_s=None,
            residuals=[], azimuthal_gap_deg=None, condition_number=None,
            ellipse_68=None, alternate_minimum=None, n_stations=len(used_station_ids),
            n_p_picks=n_p, n_s_picks=n_s, **base,
        )

    if len(used_station_ids) < MIN_STATIONS:
        return unlocatable(
            [f"有效台站数 {len(used_station_ids)} < {MIN_STATIONS}, 台站不足, 不可定位。"]
        )
    if len(used) < MIN_PICKS:
        return unlocatable(
            [f"有效到时数 {len(used)} < {MIN_PICKS}, 数据不足, 不可定位。"]
        )

    # --- 局部坐标 ---
    lat0 = float(np.mean([s.lat for _, s in used]))
    lon0 = float(np.mean([s.lon for _, s in used]))
    sta_xy = {s.id: lonlat_to_km(s.lat, s.lon, lat0, lon0) for _, s in used}

    def predicted(x: float, y: float, t0: float) -> np.ndarray:
        out = []
        for p, s in used:
            sx, sy = sta_xy[s.id]
            d = source_station_distance_km(x, y, sx, sy, model.fixed_depth_km)
            out.append(t0 + travel_time_s(d, p.phase, model))
        return np.array(out)

    obs = np.array([p.time_s for p, _ in used])
    weights = np.array([p.weight for p, _ in used])

    # --- 粗网格搜索 (对每个网格点用加权均值的解析 t0) ---
    xs = [xy[0] for xy in sta_xy.values()]
    ys = [xy[1] for xy in sta_xy.values()]
    pad = 60.0  # km, 台网外扩搜索范围
    gx = np.arange(min(xs) - pad, max(xs) + pad, 4.0)
    gy = np.arange(min(ys) - pad, max(ys) + pad, 4.0)
    rss_grid = np.full((gy.size, gx.size), np.inf)
    for ix, x in enumerate(gx):
        for iy, y in enumerate(gy):
            tt = predicted(x, y, 0.0)
            t0 = float(np.sum(weights * (obs - tt)) / np.sum(weights))
            r = (obs - tt - t0) * weights
            rss_grid[iy, ix] = float(r @ r)
    iy0, ix0 = np.unravel_index(np.argmin(rss_grid), rss_grid.shape)
    bx, by = float(gx[ix0]), float(gy[iy0])
    # 该网格点的解析 t0
    tt = predicted(bx, by, 0.0)
    bt0 = float(np.sum(weights * (obs - tt)) / np.sum(weights))

    # --- 多解诊断: 网格上的独立局部极小 (RSS 接近最优但位置远离) ---
    alternate = None
    best_rss = float(rss_grid[iy0, ix0])
    local_minima = []
    for iy in range(1, rss_grid.shape[0] - 1):
        for ix in range(1, rss_grid.shape[1] - 1):
            v = rss_grid[iy, ix]
            if v < best_rss * 1.2 and v <= rss_grid[iy - 1:iy + 2, ix - 1:ix + 2].min():
                dist = math.hypot(gx[ix] - bx, gy[iy] - by)
                local_minima.append((dist, float(v), float(gx[ix]), float(gy[iy])))
    local_minima = [m for m in local_minima if m[0] > 20.0]
    if local_minima:
        local_minima.sort(key=lambda m: m[1])
        dist, alt_rss, ax, ay = local_minima[0]
        alat, alon = km_to_lonlat(ax, ay, lat0, lon0)
        alternate = {
            "lat": alat, "lon": alon,
            "distance_from_primary_km": float(dist),
            "rss_ratio": float(alt_rss / best_rss),
            "note": "网格搜索发现拟合几乎同样好的另一个极小 (镜像模糊), "
                    "形式不确定度无法覆盖此类多解。",
        }

    # --- 最小二乘精化 (软 L1 稳健损失, 降低离群到时影响) ---
    def fun(theta):
        x, y, t0 = theta
        return (predicted(x, y, t0) - obs) * weights

    sol = least_squares(fun, [bx, by, bt0], loss="soft_l1", f_scale=1.0)
    x, y, t0 = (float(v) for v in sol.x)

    res = obs - predicted(x, y, t0)
    phases = [p.phase for p, _ in used]
    outlier_flags = _robust_outliers(res, phases)
    residuals = [
        PickResidual(
            station_id=p.station_id, phase=p.phase.upper(),
            observed_s=float(p.time_s), predicted_s=float(p.time_s - res[i]),
            residual_s=float(res[i]), is_outlier=bool(outlier_flags[i]),
        )
        for i, (p, _) in enumerate(used)
    ]
    rms = float(np.sqrt(np.mean(res**2)))

    # --- 不确定度: 由雅可比近似协方差, 给 68% 置信椭圆 ---
    J = sol.jac  # 列为 d/dx, d/dy, d/dt0 (已含权重)
    dof = max(len(used) - 3, 1)
    s2 = float((res * weights) @ (res * weights)) / dof
    ellipse = None
    cond = None
    try:
        JTJ = J.T @ J
        cond = float(np.linalg.cond(JTJ))
        cov = s2 * np.linalg.inv(JTJ)
        cov_xy = cov[:2, :2]
        eigval, eigvec = np.linalg.eigh(cov_xy)
        eigval = np.clip(eigval, 0.0, None)
        k68 = math.sqrt(2.30)  # 二维 68% 置信
        axes = k68 * np.sqrt(eigval)  # 短轴, 长轴 (km)
        angle = math.degrees(math.atan2(eigvec[0, 1], eigvec[1, 1])) % 360.0
        ellipse = {
            "semi_minor_km": float(axes[0]),
            "semi_major_km": float(axes[1]),
            "major_axis_azimuth_deg": float(angle),
            "confidence": 0.68,
        }
    except np.linalg.LinAlgError:
        pass

    # --- 几何覆盖诊断 ---
    uniq_sta_ids = {p.station_id for p, _ in used}
    azimuths = [azimuth_deg(x, y, *sta_xy[sid]) for sid in uniq_sta_ids]
    gap = _azimuthal_gap(azimuths)

    lat, lon = km_to_lonlat(x, y, lat0, lon0)
    reasons: list[str] = []
    status = "OK"
    if gap > MAX_AZIMUTHAL_GAP_DEG:
        status = "UNLOCATABLE"
        reasons.append(
            f"方位角空隙 {gap:.0f}° > {MAX_AZIMUTHAL_GAP_DEG:.0f}°, 台站几何覆盖不足 "
            f"(台站近乎共线或全在一侧), 以下数值解不可信, 仅供参考。"
        )
    if alternate is not None:
        reasons.append(
            f"存在镜像模糊解 (相距 {alternate['distance_from_primary_km']:.0f} km, "
            f"RSS 比 {alternate['rss_ratio']:.2f}), 单点坐标没有意义。"
        )
        if status == "OK":
            status = "POORLY_CONSTRAINED"
    elif cond is not None and cond > COND_WARN:
        status = "POORLY_CONSTRAINED"
        reasons.append(
            f"法方程条件数 {cond:.2e} 很大, 解对到时误差非常敏感, 不确定度被放大。"
        )
    n_out = int(outlier_flags.sum())
    if n_out:
        reasons.append(f"检测到 {n_out} 条离群到时 (残差显著偏大), 请检查人工修订。")

    return LocationResult(
        status=status, status_reasons=reasons,
        lat=lat, lon=lon, origin_time_s=t0, rms_residual_s=rms,
        residuals=residuals, azimuthal_gap_deg=gap, condition_number=cond,
        ellipse_68=ellipse, alternate_minimum=alternate, n_stations=len(used_station_ids),
        n_p_picks=n_p, n_s_picks=n_s, **base,
    )
