"""合成教学场景: 已知源位置的波形 + 到时数据。

三个案例:
1. good-geometry     台站包围震源, 干净到时 —— 标准可定位情形
2. outlier-picks     同一几何, 自动拾取含两条离群到时 —— 残差暴露问题,
                     人工修订 (revised) 与原始拾取 (raw) 分开保存
3. collinear-stations 台站几乎共线 —— 方位角空隙过大, 引擎报告不可定位

波形用 ObsPy Trace 打包 (可导出 MiniSEED), 到时真值由速度模型正演。
"""
from __future__ import annotations

import numpy as np
from obspy import Trace

from .locate import Pick, Station
from .travel_time import lonlat_to_km, source_station_distance_km, travel_time_s
from .velocity_model import DEFAULT_MODEL, VelocityModel

SAMPLE_RATE = 50.0        # Hz
TRACE_DURATION_S = 120.0  # 每条波形时长

# 数据版本: 场景定义变更时手动递增, 与定位结果绑定
SCENARIO_DATA_VERSION = "synthetic-scenarios-v1.2"


def synth_trace_arrays(
    tp_s: float, ts_s: float, seed: int, duration: float = TRACE_DURATION_S,
    sr: float = SAMPLE_RATE,
) -> tuple[np.ndarray, np.ndarray]:
    """合成单台波形: 高斯噪声 + P 波小振幅高频波列 + S 波大振幅低频波列。"""
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, duration, 1.0 / sr)
    y = 0.05 * rng.standard_normal(t.size)
    p = t >= tp_s
    y[p] += 0.5 * np.exp(-(t[p] - tp_s) / 2.0) * np.sin(2 * np.pi * 3.0 * (t[p] - tp_s))
    s = t >= ts_s
    y[s] += 1.2 * np.exp(-(t[s] - ts_s) / 4.0) * np.sin(2 * np.pi * 1.2 * (t[s] - ts_s))
    return t, y


def to_obspy_trace(y: np.ndarray, station_id: str, sr: float = SAMPLE_RATE) -> Trace:
    tr = Trace(data=np.asarray(y, dtype=np.float32))
    tr.stats.station = station_id
    tr.stats.channel = "BHZ"
    tr.stats.sampling_rate = sr
    return tr


class Scenario:
    def __init__(self, id, title, description, teaching_points, source, stations,
                 raw_picks, revised_picks, seed):
        self.id = id
        self.title = title
        self.description = description
        self.teaching_points = teaching_points
        self.source = source            # {"lat","lon","origin_time_s","depth_km"} 真值
        self.stations: dict[str, Station] = {s.id: s for s in stations}
        self.raw_picks: list[Pick] = raw_picks
        self.revised_picks: list[Pick] = revised_picks
        self.seed = seed


def _true_picks(source, stations, model, rng, noise_s=0.15) -> list[Pick]:
    """按真值正演到时并加拾取噪声, 每台 P、S 各一条。"""
    picks = []
    lat0, lon0 = source["lat"], source["lon"]
    for sta in stations:
        sx, sy = lonlat_to_km(sta.lat, sta.lon, lat0, lon0)
        d = source_station_distance_km(0.0, 0.0, sx, sy, source["depth_km"])
        for phase in ("P", "S"):
            t = source["origin_time_s"] + travel_time_s(d, phase, model)
            t += float(rng.normal(0.0, noise_s))
            picks.append(Pick(station_id=sta.id, phase=phase, time_s=round(t, 3)))
    return picks


def _ring_stations(lat0, lon0, radii_km, n, seed, prefix="ST") -> list[Station]:
    rng = np.random.default_rng(seed)
    stations = []
    for i in range(n):
        az = 2 * np.pi * i / n + rng.normal(0, 0.08)
        r = radii_km * (0.8 + 0.4 * rng.random())
        dlat = r * np.cos(az) / 111.195
        dlon = r * np.sin(az) / (111.195 * np.cos(np.radians(lat0)))
        stations.append(Station(id=f"{prefix}{i+1:02d}", name=f"{prefix}{i+1:02d}",
                                lat=lat0 + dlat, lon=lon0 + dlon))
    return stations


def build_scenarios(model: VelocityModel = DEFAULT_MODEL) -> dict[str, Scenario]:
    scenarios: dict[str, Scenario] = {}

    # --- 案例 1: 良好几何 ---
    src1 = {"lat": 31.05, "lon": 103.40, "origin_time_s": 20.0, "depth_km": model.fixed_depth_km}
    stas1 = _ring_stations(31.0, 103.4, 90.0, n=8, seed=11)
    rng1 = np.random.default_rng(101)
    raw1 = _true_picks(src1, stas1, model, rng1)
    scenarios["good-geometry"] = Scenario(
        id="good-geometry",
        title="案例 1: 良好台站几何",
        description="8 个台站近似包围震源, P/S 到时干净。用于演示标准定位流程、"
                    "残差分布与 68% 置信椭圆。",
        teaching_points=[
            "定位结果是不确定度椭圆而非精确点",
            "P 与 S 走时分别由各自速度计算",
            "RMS 残差反映拾取与模型的整体一致性",
        ],
        source=src1, stations=stas1,
        raw_picks=raw1, revised_picks=[Pick(p.station_id, p.phase, p.time_s) for p in raw1],
        seed=1001,
    )

    # --- 案例 2: 离群到时 ---
    src2 = {"lat": 30.90, "lon": 103.55, "origin_time_s": 20.0, "depth_km": model.fixed_depth_km}
    stas2 = _ring_stations(30.9, 103.5, 95.0, n=8, seed=22)
    rng2 = np.random.default_rng(202)
    raw2 = _true_picks(src2, stas2, model, rng2)
    # 模拟自动拾取器错误: 两条到时严重偏差 (raw 保留错误, revised 为人工修订后)
    outlier_idx = [3, 11]  # 一条 P 一条 S
    revised2 = [Pick(p.station_id, p.phase, p.time_s) for p in raw2]
    for k, idx in enumerate(outlier_idx):
        raw2[idx].time_s = round(raw2[idx].time_s + (3.8 if k == 0 else -3.1), 3)
    scenarios["outlier-picks"] = Scenario(
        id="outlier-picks",
        title="案例 2: 离群到时 (自动拾取错误)",
        description="与案例 1 类似的几何, 但原始自动拾取中混入两条严重错误的到时。 "
                    "raw 解被拉偏且残差暴露离群值; revised 为人工修订后的到时, 两阶段分开保存。",
        teaching_points=[
            "逐台残差是发现错误拾取的第一手段",
            "原始拾取与人工修订必须分开存储、分别定位",
            "稳健估计减轻但不能替代人工检查",
        ],
        source=src2, stations=stas2,
        raw_picks=raw2, revised_picks=revised2,
        seed=2002,
    )

    # --- 案例 3: 台站几乎共线 ---
    src3 = {"lat": 31.0 + 15.0 / 111.195, "lon": 104.10,
            "origin_time_s": 20.0, "depth_km": model.fixed_depth_km}
    rng3 = np.random.default_rng(303)
    stas3 = []
    for i in range(6):  # 沿一条近东西向线排列 (横向散布仅 ~1 km)
        dx = -120.0 + i * 45.0 + rng3.normal(0, 3.0)
        dy = rng3.normal(0, 1.0)
        stas3.append(Station(
            id=f"LN{i+1:02d}", name=f"LN{i+1:02d}",
            lat=31.0 + dy / 111.195,
            lon=103.8 + dx / (111.195 * np.cos(np.radians(31.0))),
        ))
    raw3 = _true_picks(src3, stas3, model, np.random.default_rng(404))
    scenarios["collinear-stations"] = Scenario(
        id="collinear-stations",
        title="案例 3: 台站几乎共线 (不可定位)",
        description="6 个台站近似排成一条直线, 震源位于线外。方位角空隙远超 180°, "
                    "且走时残差面存在镜像双极小 —— 引擎明确报告 UNLOCATABLE 而非给出假精确解。",
        teaching_points=[
            "方位角空隙是几何覆盖的核心指标",
            "共线台阵产生镜像模糊解, 形式置信椭圆无法表达",
            "诚实的'不可定位'优于虚假的精确坐标",
        ],
        source=src3, stations=stas3,
        raw_picks=raw3, revised_picks=[Pick(p.station_id, p.phase, p.time_s) for p in raw3],
        seed=3003,
    )

    return scenarios
