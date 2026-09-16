"""SQL 持久化仓库: 台站 / 两阶段拾取 / 修订历史 / 定位结果历史。

通过 SQLAlchemy 支持 PostgreSQL (生产, 含 PostGIS 扩展列) 与 SQLite (测试)。
raw 拾取在本层拒绝任何修改, PostgreSQL 上另有数据库触发器兜底。
"""
from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..core.locate import LocationResult, Pick, Station
from ..core.synthetic import SCENARIO_DATA_VERSION, Scenario, build_scenarios
from ..core.velocity_model import DEFAULT_MODEL
from .migrate import migrate
from .models import (
    PickRevisionRow, PickRow, ScenarioRow, SolutionRow, StationRow,
)


class RawPickImmutableError(Exception):
    """试图修改 raw (原始自动拾取) 时抛出。"""


class SQLStore:
    """场景存储的 SQL 实现, 接口与内存实现一致 (见 app/store.py)。"""

    def __init__(self, database_url: str):
        # postgresql:// 统一走 psycopg (v3) 驱动
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1)
        self.engine: Engine = create_engine(database_url, future=True)
        migrate(self.engine)
        self.data_version = SCENARIO_DATA_VERSION
        self._seed_if_empty()

    # ---------- 种子 ----------
    def _seed_if_empty(self) -> None:
        with Session(self.engine) as s:
            if s.query(ScenarioRow).count() > 0:
                return
            for sc in build_scenarios(DEFAULT_MODEL).values():
                s.add(ScenarioRow(
                    id=sc.id, title=sc.title, description=sc.description,
                    teaching_points=sc.teaching_points,
                    data_version=self.data_version,
                    true_source=sc.source, seed=sc.seed,
                ))
                for sta in sc.stations.values():
                    s.add(StationRow(scenario_id=sc.id, id=sta.id, name=sta.name,
                                     lat=sta.lat, lon=sta.lon))
                for stage, picks in (("raw", sc.raw_picks),
                                     ("revised", sc.revised_picks)):
                    for p in picks:
                        s.add(PickRow(
                            scenario_id=sc.id, station_id=p.station_id,
                            stage=stage, phase=p.phase.upper(),
                            time_s=p.time_s, weight=p.weight,
                        ))
            s.commit()

    # ---------- 读取 ----------
    def _to_domain(self, s: Session, row: ScenarioRow) -> Scenario:
        picks = s.execute(
            select(PickRow).where(PickRow.scenario_id == row.id)
        ).scalars().all()
        raw = [Pick(p.station_id, p.phase, p.time_s, p.weight)
               for p in picks if p.stage == "raw"]
        revised = [Pick(p.station_id, p.phase, p.time_s, p.weight)
                   for p in picks if p.stage == "revised"]
        sta_ids = {p.station_id for p in picks}
        stations = []
        for sid in sta_ids:
            sta = s.get(StationRow, (row.id, sid))
            stations.append(Station(sta.id, sta.name, sta.lat, sta.lon))
        return Scenario(
            id=row.id, title=row.title, description=row.description,
            teaching_points=list(row.teaching_points), source=dict(row.true_source),
            stations=stations, raw_picks=raw, revised_picks=revised, seed=row.seed,
        )

    def list(self) -> list[Scenario]:
        with Session(self.engine) as s:
            rows = s.execute(select(ScenarioRow)).scalars().all()
            return [self._to_domain(s, r) for r in rows]

    def get(self, scenario_id: str) -> Scenario | None:
        with Session(self.engine) as s:
            row = s.get(ScenarioRow, scenario_id)
            return self._to_domain(s, row) if row else None

    # ---------- 写入: 仅 revised 可写 ----------
    def update_revised_picks(self, scenario_id: str, picks: list[Pick],
                             author: str | None = None) -> Scenario | None:
        with Session(self.engine) as s:
            if s.get(ScenarioRow, scenario_id) is None:
                return None
            existing = s.execute(
                select(PickRow).where(
                    PickRow.scenario_id == scenario_id,
                    PickRow.stage == "revised",
                )
            ).scalars().all()
            by_key = {(p.station_id, p.phase): p for p in existing}
            seen = set()
            for p in picks:
                key = (p.station_id, p.phase.upper())
                seen.add(key)
                row = by_key.get(key)
                if row is None:
                    s.add(PickRow(scenario_id=scenario_id, station_id=p.station_id,
                                  stage="revised", phase=p.phase.upper(),
                                  time_s=p.time_s, weight=p.weight,
                                  author=author))
                else:
                    row.time_s = p.time_s
                    row.weight = p.weight
                    row.author = author
                # 追加修订历史 (每次保存都留痕)
                s.add(PickRevisionRow(
                    scenario_id=scenario_id, station_id=p.station_id,
                    phase=p.phase.upper(), time_s=p.time_s, weight=p.weight,
                    author=author,
                ))
            # revised 集合以提交为准: 删除未包含的旧修订行
            for row in existing:
                if (row.station_id, row.phase) not in seen:
                    s.delete(row)
            s.commit()
        return self.get(scenario_id)

    def update_raw_picks(self, *args, **kwargs):
        raise RawPickImmutableError("raw 拾取不可修改: 原始自动拾取只读")

    # ---------- 定位结果历史 ----------
    def save_solutions(self, scenario_id: str,
                       results: dict[str, LocationResult]) -> None:
        with Session(self.engine) as s:
            for stage, res in results.items():
                d = asdict(res)
                residuals = d.pop("residuals")
                reasons = d.pop("status_reasons")
                s.add(SolutionRow(
                    scenario_id=scenario_id, stage=stage,
                    status=d.pop("status"), status_reasons=reasons,
                    residuals=residuals, **d,
                ))
            s.commit()

    def list_solutions(self, scenario_id: str) -> list[dict]:
        with Session(self.engine) as s:
            rows = s.execute(
                select(SolutionRow)
                .where(SolutionRow.scenario_id == scenario_id)
                .order_by(SolutionRow.id.desc())
            ).scalars().all()
            out = []
            for r in rows:
                out.append({
                    "id": r.id, "scenario_id": r.scenario_id, "stage": r.stage,
                    "status": r.status, "status_reasons": r.status_reasons,
                    "lat": r.lat, "lon": r.lon, "depth_km": r.depth_km,
                    "origin_time_s": r.origin_time_s,
                    "rms_residual_s": r.rms_residual_s,
                    "azimuthal_gap_deg": r.azimuthal_gap_deg,
                    "condition_number": r.condition_number,
                    "ellipse_68": r.ellipse_68,
                    "alternate_minimum": r.alternate_minimum,
                    "residuals": r.residuals,
                    "n_stations": r.n_stations,
                    "n_p_picks": r.n_p_picks, "n_s_picks": r.n_s_picks,
                    "model_version": r.model_version,
                    "engine_version": r.engine_version,
                    "data_version": r.data_version,
                    "disclaimer": r.disclaimer,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })
            return out

    def list_pick_revisions(self, scenario_id: str) -> list[dict]:
        with Session(self.engine) as s:
            rows = s.execute(
                select(PickRevisionRow)
                .where(PickRevisionRow.scenario_id == scenario_id)
                .order_by(PickRevisionRow.id.desc())
            ).scalars().all()
            return [{
                "id": r.id, "station_id": r.station_id, "phase": r.phase,
                "time_s": r.time_s, "weight": r.weight, "author": r.author,
                "saved_at": r.saved_at.isoformat() if r.saved_at else None,
            } for r in rows]
