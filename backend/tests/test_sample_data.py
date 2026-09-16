"""MiniSEED 示例数据解析入口测试。"""
import numpy as np
import pytest
from obspy import read, read_inventory

from app.core import sample_data
from app.core.synthetic import build_scenarios
from app.core.velocity_model import DEFAULT_MODEL


@pytest.fixture(scope="module")
def scenarios():
    sc = build_scenarios(DEFAULT_MODEL)
    sample_data.ensure_sample_data(list(sc.values()))
    return sc


def test_sample_files_exist_and_parse(scenarios):
    for sid in ("good-geometry", "outlier-picks", "collinear-stations"):
        assert sample_data.mseed_path(sid).exists()
        assert sample_data.stationxml_path(sid).exists()
        st = read(str(sample_data.mseed_path(sid)))  # 真实解析入口
        inv = read_inventory(str(sample_data.stationxml_path(sid)))
        assert len(st) == len(scenarios[sid].stations)
        assert len(inv[0].stations) == len(scenarios[sid].stations)
        for tr in st:
            assert tr.stats.sampling_rate == 50.0
            assert tr.stats.channel == "BHZ"


def test_parsed_waveforms_match_picks(scenarios):
    """解析出的波形中 P/S 波列位置应与拾取到时一致 (±0.5 s)。"""
    sc = scenarios["good-geometry"]
    parsed = sample_data.parse_waveforms("good-geometry")
    picks = {}
    for p in sc.raw_picks:
        picks.setdefault(p.station_id, {})[p.phase] = p.time_s
    checked = 0
    for sta_id, (t, y) in parsed.items():
        env = np.abs(y)
        for phase in ("P", "S"):
            tpick = picks[sta_id][phase]
            # 拾取时刻后 3 s 窗内应出现明显能量
            win = env[(t >= tpick) & (t <= tpick + 3.0)]
            pre = env[(t >= tpick - 5.0) & (t < tpick - 0.5)]
            # 波列能量显著高于噪声 (P 振幅 0.5 / S 振幅 1.2, 噪声 σ=0.05)
            assert win.max() > 2.0 * pre.max() and win.max() > 0.3, \
                f"{sta_id} {phase} 波列未在拾取时刻附近"
            checked += 1
    assert checked == 16


def test_parsed_stations_match_scenario(scenarios):
    sc = scenarios["good-geometry"]
    stations = {s["station"]: s for s in sample_data.parse_stations("good-geometry")}
    assert set(stations) == set(sc.stations)
    for sid, sta in sc.stations.items():
        assert abs(stations[sid]["lat"] - sta.lat) < 1e-6
        assert abs(stations[sid]["lon"] - sta.lon) < 1e-6
