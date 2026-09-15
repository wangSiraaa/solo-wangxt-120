"""平直地球近似下的几何与走时计算。

坐标转换采用局部切平面近似 (等距圆柱), 适用于教学场景的小区域台网。
走时 = 源台距(含固定深度) / 震相速度。
"""
from __future__ import annotations

import math

KM_PER_DEG_LAT = 111.195


def lonlat_to_km(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """以 (lat0, lon0) 为原点, 返回 (x_east_km, y_north_km)。"""
    x = (lon - lon0) * KM_PER_DEG_LAT * math.cos(math.radians(lat0))
    y = (lat - lat0) * KM_PER_DEG_LAT
    return x, y


def km_to_lonlat(x_km: float, y_km: float, lat0: float, lon0: float) -> tuple[float, float]:
    lat = lat0 + y_km / KM_PER_DEG_LAT
    lon = lon0 + x_km / (KM_PER_DEG_LAT * math.cos(math.radians(lat0)))
    return lat, lon


def source_station_distance_km(
    sx_km: float, sy_km: float, sta_x_km: float, sta_y_km: float, depth_km: float
) -> float:
    epi2 = (sx_km - sta_x_km) ** 2 + (sy_km - sta_y_km) ** 2
    return math.sqrt(epi2 + depth_km**2)


def travel_time_s(distance_km: float, phase: str, model) -> float:
    """按震相走时。速度取自模型, P/S 严格分离。"""
    return distance_km / model.velocity_for_phase(phase)


def azimuth_deg(sx_km: float, sy_km: float, tx_km: float, ty_km: float) -> float:
    """从 (sx,sy) 指向 (tx,ty) 的方位角, 北为 0, 顺时针。"""
    return math.degrees(math.atan2(tx_km - sx_km, ty_km - sy_km)) % 360.0
