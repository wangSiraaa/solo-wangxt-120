"""MiniSEED 示例数据: 生成、落盘与解析入口。

sample_data/ 下每个场景两个文件:
- <scenario_id>.mseed        波形 (ObsPy 写出, STEIM 压缩)
- <scenario_id>.stations.xml 台站元数据 (StationXML)

解析一律通过 obspy.read / obspy.read_inventory —— 与处理真实数据的工具链一致,
而不是直接返回内存数组。文件由确定性种子生成, 缺失时启动自动重建。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from obspy import Inventory, Stream, UTCDateTime
from obspy.core.inventory import Network, Station as InvStation
from obspy import read, read_inventory

from .synthetic import SAMPLE_RATE, synth_trace_arrays, to_obspy_trace

SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "sample_data"
TRACE_START = UTCDateTime("2020-01-01T00:00:00")
NETWORK = "GT"


def mseed_path(scenario_id: str) -> Path:
    return SAMPLE_DATA_DIR / f"{scenario_id}.mseed"


def stationxml_path(scenario_id: str) -> Path:
    return SAMPLE_DATA_DIR / f"{scenario_id}.stations.xml"


def write_sample_data(scenario) -> None:
    """把场景的合成波形与台站元数据写成 MiniSEED + StationXML 示例文件。"""
    from .travel_time import lonlat_to_km, source_station_distance_km, travel_time_s
    from .velocity_model import DEFAULT_MODEL

    SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    src = scenario.source
    stream = Stream()
    inv_stations = []
    for i, sta in enumerate(scenario.stations.values()):
        sx, sy = lonlat_to_km(sta.lat, sta.lon, src["lat"], src["lon"])
        d = source_station_distance_km(0.0, 0.0, sx, sy, src["depth_km"])
        tp = src["origin_time_s"] + travel_time_s(d, "P", DEFAULT_MODEL)
        ts = src["origin_time_s"] + travel_time_s(d, "S", DEFAULT_MODEL)
        _, y = synth_trace_arrays(tp, ts, seed=scenario.seed + i)
        tr = to_obspy_trace(y, sta.id)
        tr.stats.network = NETWORK
        tr.stats.starttime = TRACE_START
        stream += tr
        inv_stations.append(InvStation(
            code=sta.id, latitude=sta.lat, longitude=sta.lon, elevation=0.0,
            creation_date=TRACE_START,
        ))
    stream.write(str(mseed_path(scenario.id)), format="MSEED")
    inv = Inventory(
        networks=[Network(code=NETWORK, stations=inv_stations)],
        source="geoteach-synthetic",
    )
    inv.write(str(stationxml_path(scenario.id)), format="STATIONXML")


def ensure_sample_data(scenarios) -> None:
    """缺失文件时重建 (确定性种子, 内容可复现)。"""
    for sc in scenarios:
        if not mseed_path(sc.id).exists() or not stationxml_path(sc.id).exists():
            write_sample_data(sc)


def parse_waveforms(scenario_id: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """用 obspy.read 解析 MiniSEED, 返回 {station_id: (t_relative_s, y)}。"""
    path = mseed_path(scenario_id)
    if not path.exists():
        raise FileNotFoundError(f"示例数据文件缺失: {path}")
    st = read(str(path))  # 真实解析入口, 非内存数组
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for tr in st:
        sr = tr.stats.sampling_rate
        t = np.arange(tr.stats.npts) / sr
        out[tr.stats.station] = (t, tr.data.astype(np.float64))
    return out


def parse_stations(scenario_id: str) -> list[dict]:
    """用 obspy.read_inventory 解析 StationXML 台站元数据。"""
    path = stationxml_path(scenario_id)
    if not path.exists():
        raise FileNotFoundError(f"台站元数据文件缺失: {path}")
    inv = read_inventory(str(path))
    stations = []
    for net in inv:
        for sta in net:
            stations.append({
                "network": net.code,
                "station": sta.code,
                "lat": sta.latitude,
                "lon": sta.longitude,
                "elevation_m": sta.elevation,
            })
    return stations
