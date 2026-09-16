"""SQL 持久层测试: CRUD、raw 不可变、revised 持久化、版本/历史、重启读回。

默认用 SQLite 文件库验证语义 (模拟容器重启: 同一文件重新建连接)。
设置 TEST_DATABASE_URL=postgresql+psycopg://... 时另跑真实 PostgreSQL 集成测试。
"""
import os

import pytest

from app.core.locate import Pick, locate
from app.core.velocity_model import DEFAULT_MODEL
from app.db.repo import RawPickImmutableError, SQLStore


def make_store(tmp_path, name="test.db"):
    return SQLStore(f"sqlite:///{tmp_path}/{name}")


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path


def test_seed_creates_three_scenarios(db_path):
    store = make_store(db_path)
    scenarios = {sc.id: sc for sc in store.list()}
    assert set(scenarios) == {"good-geometry", "outlier-picks", "collinear-stations"}
    good = scenarios["good-geometry"]
    assert len(good.stations) == 8
    assert len(good.raw_picks) == 16
    assert {p.phase for p in good.raw_picks} == {"P", "S"}
    assert good.source["lat"] is not None


def test_revised_persisted_raw_untouched(db_path):
    store = make_store(db_path)
    sc = store.get("good-geometry")
    raw_before = sorted((p.station_id, p.phase, p.time_s) for p in sc.raw_picks)

    new_picks = [Pick(p.station_id, p.phase, round(p.time_s + 0.25, 3))
                 for p in sc.revised_picks]
    store.update_revised_picks("good-geometry", new_picks, author="student-a")

    after = store.get("good-geometry")
    raw_after = sorted((p.station_id, p.phase, p.time_s) for p in after.raw_picks)
    assert raw_after == raw_before, "raw 拾取不得被修订操作改变"
    assert abs(after.revised_picks[0].time_s - new_picks[0].time_s) < 1e-9

    hist = store.list_pick_revisions("good-geometry")
    assert len(hist) == len(new_picks)
    assert all(h["author"] == "student-a" for h in hist)


def test_raw_update_rejected(db_path):
    store = make_store(db_path)
    with pytest.raises(RawPickImmutableError):
        store.update_raw_picks("good-geometry", [])


def test_solutions_history_with_versions(db_path):
    store = make_store(db_path)
    sc = store.get("good-geometry")
    res = locate(sc.raw_picks, sc.stations, DEFAULT_MODEL)
    store.save_solutions("good-geometry", {"raw": res})
    store.save_solutions("good-geometry", {"raw": res})  # 再跑一次 → 两条历史

    hist = store.list_solutions("good-geometry")
    assert len(hist) == 2
    for h in hist:
        assert h["model_version"] == DEFAULT_MODEL.version
        assert h["engine_version"]
        assert h["data_version"] == res.data_version
        assert h["status"] == "OK"
        assert len(h["residuals"]) == 16


def test_restart_reads_back_revisions_and_history(db_path):
    """模拟容器重启: 同一数据库文件新建 SQLStore, 修订与历史结果仍可读回。"""
    store1 = make_store(db_path)
    sc = store1.get("outlier-picks")
    modified = [Pick(p.station_id, p.phase, p.time_s) for p in sc.revised_picks]
    modified[0].time_s = round(modified[0].time_s + 0.5, 3)
    store1.update_revised_picks("outlier-picks", modified, author="student-b")
    res = locate(modified, sc.stations, DEFAULT_MODEL)
    store1.save_solutions("outlier-picks", {"revised": res})
    del store1  # 关闭旧连接, 模拟容器停止

    store2 = make_store(db_path)  # "重启" 后重新连接同一数据库
    sc2 = store2.get("outlier-picks")
    assert abs(sc2.revised_picks[0].time_s - modified[0].time_s) < 1e-9
    hist = store2.list_solutions("outlier-picks")
    assert len(hist) == 1
    assert hist[0]["stage"] == "revised"
    assert hist[0]["model_version"] == DEFAULT_MODEL.version
    assert hist[0]["data_version"] == res.data_version
    rev = store2.list_pick_revisions("outlier-picks")
    assert any(r["author"] == "student-b" for r in rev)


def test_unknown_scenario_returns_none(db_path):
    store = make_store(db_path)
    assert store.get("no-such") is None
    assert store.update_revised_picks("no-such", []) is None


# --- 真实 PostgreSQL 集成测试 (需要 TEST_DATABASE_URL) ---
PG_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_URL, reason="未设置 TEST_DATABASE_URL, 跳过 PostgreSQL 集成测试")
def test_postgresql_roundtrip():
    store = SQLStore(PG_URL)
    sc = store.get("good-geometry")
    assert sc is not None and len(sc.stations) == 8
    res = locate(sc.raw_picks, sc.stations, DEFAULT_MODEL)
    store.save_solutions("good-geometry", {"raw": res})
    hist = store.list_solutions("good-geometry")
    assert hist and hist[0]["model_version"] == DEFAULT_MODEL.version
