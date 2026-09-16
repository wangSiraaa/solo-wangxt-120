"""API 直接回归: 三场景定位、P/S 分速、残差展示、示例数据入口、历史读回。

使用默认内存存储 (未设 DATABASE_URL), 验证现有 API 行为保持不变。
"""
import math

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # 触发 startup: 确保示例数据文件存在
        yield c


def test_three_scenarios_listed(client):
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()}
    assert ids == {"good-geometry", "outlier-picks", "collinear-stations"}


def test_good_geometry_ok_with_residuals(client):
    r = client.post("/api/scenarios/good-geometry/locate").json()
    res = r["results"]["raw"]
    assert res["status"] == "OK"
    assert res["rms_residual_s"] < 0.5
    assert len(res["residuals"]) == 16
    assert {x["phase"] for x in res["residuals"]} == {"P", "S"}
    assert res["ellipse_68"]["semi_major_km"] > 0
    assert res["model_version"] == "homogeneous-halfspace-v1"
    assert "不构成真实地震预警" in res["disclaimer"]


def test_outlier_scenario_raw_vs_revised(client):
    r = client.post("/api/scenarios/outlier-picks/locate").json()
    raw, rev = r["results"]["raw"], r["results"]["revised"]
    assert sum(1 for x in raw["residuals"] if x["is_outlier"]) >= 1
    assert rev["rms_residual_s"] < raw["rms_residual_s"]


def test_collinear_unlocatable(client):
    r = client.post("/api/scenarios/collinear-stations/locate").json()
    res = r["results"]["raw"]
    assert res["status"] == "UNLOCATABLE"
    assert res["azimuthal_gap_deg"] > 180
    assert res["alternate_minimum"] is not None


def test_waveforms_come_from_mseed_parse(client):
    r = client.get("/api/scenarios/good-geometry/waveforms")
    assert r.status_code == 200
    wf = r.json()
    assert len(wf) == 8
    assert len(wf[0]["t"]) == len(wf[0]["y"]) > 1000


def test_sample_data_entry_returns_parsed_waveforms_and_stations(client):
    r = client.get("/api/scenarios/good-geometry/sample-data")
    assert r.status_code == 200
    d = r.json()
    assert d["files"]["mseed"] == "good-geometry.mseed"
    assert "obspy.read" in d["parsed_with"]
    assert len(d["stations"]) == 8
    assert all("lat" in s and "lon" in s for s in d["stations"])
    assert len(d["waveforms"]) == 8


def test_mseed_download(client):
    r = client.get("/api/scenarios/good-geometry/waveforms.mseed")
    assert r.status_code == 200
    assert len(r.content) > 10000


def test_revised_update_and_history_flow(client):
    # 取当前 revised
    picks = client.get("/api/scenarios/good-geometry/picks").json()
    revised = picks["revised"]
    revised[0]["time_s"] = round(revised[0]["time_s"] + 0.3, 3)
    body = {"picks": [{k: p[k] for k in ("station_id", "phase", "time_s", "weight")}
                      for p in revised],
            "author": "tester"}
    r = client.put("/api/scenarios/good-geometry/picks/revised", json=body)
    assert r.status_code == 200

    # raw 未变
    picks2 = client.get("/api/scenarios/good-geometry/picks").json()
    assert abs(picks2["revised"][0]["time_s"] - revised[0]["time_s"]) < 1e-9

    # 定位后历史可读回, 且绑定版本
    client.post("/api/scenarios/good-geometry/locate")
    hist = client.get("/api/scenarios/good-geometry/locate/history").json()
    assert len(hist) >= 2  # raw + revised
    for h in hist:
        assert h["model_version"] == "homogeneous-halfspace-v1"
        assert h["data_version"]

    # 修订历史留痕
    rev = client.get("/api/scenarios/good-geometry/picks/revisions").json()
    assert any(x.get("author") == "tester" for x in rev)


def test_unknown_phase_rejected_by_api(client):
    body = {"picks": [{"station_id": "ST01", "phase": "Pg", "time_s": 25.0}]}
    r = client.put("/api/scenarios/good-geometry/picks/revised", json=body)
    assert r.status_code == 422  # pydantic 校验: 仅允许 P/S
