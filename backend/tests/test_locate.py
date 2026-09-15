"""定位引擎单元测试。"""
import math

import pytest

from app.core.locate import MIN_STATIONS, Pick, locate
from app.core.synthetic import build_scenarios
from app.core.velocity_model import DEFAULT_MODEL


@pytest.fixture(scope="module")
def scenarios():
    return build_scenarios()


def _sta_map(sc):
    return sc.stations


def test_good_geometry_recovers_source(scenarios):
    sc = scenarios["good-geometry"]
    res = locate(sc.raw_picks, _sta_map(sc), DEFAULT_MODEL)
    assert res.status == "OK"
    # 震中误差应在数 km 内 (拾取噪声 0.15 s)
    dlat = (res.lat - sc.source["lat"]) * 111.195
    dlon = (res.lon - sc.source["lon"]) * 111.195 * math.cos(math.radians(sc.source["lat"]))
    dist_km = math.hypot(dlat, dlon)
    assert dist_km < 8.0, f"震中偏差 {dist_km:.1f} km 过大"
    assert abs(res.origin_time_s - sc.source["origin_time_s"]) < 1.0
    assert res.rms_residual_s < 0.5
    assert res.ellipse_68 is not None
    assert res.azimuthal_gap_deg < 180.0
    assert res.model_version == DEFAULT_MODEL.version
    assert res.data_version


def test_outlier_picks_flagged_and_fixed_by_revision(scenarios):
    sc = scenarios["outlier-picks"]
    raw_res = locate(sc.raw_picks, _sta_map(sc), DEFAULT_MODEL)
    rev_res = locate(sc.revised_picks, _sta_map(sc), DEFAULT_MODEL)
    # raw 解应标记出离群到时
    outliers = [r for r in raw_res.residuals if r.is_outlier]
    assert len(outliers) >= 1, "raw 解应检测出离群到时"
    # 修订后残差显著改善、更靠近真值
    assert rev_res.rms_residual_s < raw_res.rms_residual_s
    dlat = (rev_res.lat - sc.source["lat"]) * 111.195
    dlon = (rev_res.lon - sc.source["lon"]) * 111.195 * math.cos(math.radians(sc.source["lat"]))
    assert math.hypot(dlat, dlon) < 8.0


def test_collinear_stations_unlocatable(scenarios):
    sc = scenarios["collinear-stations"]
    res = locate(sc.raw_picks, _sta_map(sc), DEFAULT_MODEL)
    assert res.status == "UNLOCATABLE"
    assert res.azimuthal_gap_deg > 180.0
    assert any("方位角空隙" in r for r in res.status_reasons)
    # 仍给出参考数值解供教学讨论, 且必须暴露镜像模糊解
    assert res.lat is not None
    assert res.alternate_minimum is not None
    assert res.alternate_minimum["distance_from_primary_km"] > 20.0
    assert any("镜像" in r for r in res.status_reasons)


def test_too_few_stations_unlocatable(scenarios):
    sc = scenarios["good-geometry"]
    few = [p for p in sc.raw_picks if p.station_id in ("ST01", "ST02")]
    res = locate(few, _sta_map(sc), DEFAULT_MODEL)
    assert res.status == "UNLOCATABLE"
    assert res.lat is None
    assert any("台站不足" in r for r in res.status_reasons)


def test_unknown_phase_rejected(scenarios):
    sc = scenarios["good-geometry"]
    bad = [Pick("ST01", "Pg", 25.0)]  # 地壳折射相等未建模震相不允许混入
    with pytest.raises(ValueError, match="不允许混用"):
        locate(bad + sc.raw_picks, _sta_map(sc), DEFAULT_MODEL)


def test_p_and_s_use_different_velocities():
    vp = DEFAULT_MODEL.velocity_for_phase("P")
    vs = DEFAULT_MODEL.velocity_for_phase("S")
    assert vp > vs
    assert abs(vp / vs - 1.73) < 1e-6


def test_data_version_changes_with_picks(scenarios):
    sc = scenarios["good-geometry"]
    r1 = locate(sc.raw_picks, _sta_map(sc), DEFAULT_MODEL)
    modified = [Pick(p.station_id, p.phase, p.time_s) for p in sc.raw_picks]
    modified[0].time_s += 0.5
    r2 = locate(modified, _sta_map(sc), DEFAULT_MODEL)
    assert r1.data_version != r2.data_version
    assert r1.model_version == r2.model_version
