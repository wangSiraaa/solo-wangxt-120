"""场景存储工厂。

- 设置 DATABASE_URL 时: SQLStore (PostgreSQL/PostGIS 生产链路, 或 SQLite 测试)
- 否则: InMemoryStore (课堂快速启动)

两种实现接口一致, API 层不感知差异。
"""
from __future__ import annotations

import os
from dataclasses import asdict

from .core.locate import LocationResult, Pick
from .core.synthetic import SCENARIO_DATA_VERSION, Scenario, build_scenarios
from .core.velocity_model import DEFAULT_MODEL


class InMemoryStore:
    """内存场景存储 (默认): 接口与 SQLStore 一致, 重启不保留。"""

    def __init__(self):
        self._scenarios: dict[str, Scenario] = build_scenarios(DEFAULT_MODEL)
        self._solutions: dict[str, list[dict]] = {}
        self._pick_revisions: dict[str, list[dict]] = {}
        self.data_version = SCENARIO_DATA_VERSION

    def list(self) -> list[Scenario]:
        return list(self._scenarios.values())

    def get(self, scenario_id: str) -> Scenario | None:
        return self._scenarios.get(scenario_id)

    def update_revised_picks(self, scenario_id: str, picks: list[Pick],
                             author: str | None = None) -> Scenario | None:
        """保存人工修订到时。raw 永不被修改 —— 两阶段严格分离。"""
        sc = self._scenarios.get(scenario_id)
        if sc is None:
            return None
        sc.revised_picks = picks
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        hist = self._pick_revisions.setdefault(scenario_id, [])
        for p in picks:
            hist.append({"station_id": p.station_id, "phase": p.phase,
                         "time_s": p.time_s, "weight": p.weight,
                         "author": author, "saved_at": now})
        return sc

    def update_raw_picks(self, *args, **kwargs):
        raise PermissionError("raw 拾取不可修改: 原始自动拾取只读")

    def save_solutions(self, scenario_id: str,
                       results: dict[str, LocationResult]) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        hist = self._solutions.setdefault(scenario_id, [])
        for stage, res in results.items():
            d = asdict(res)
            d["scenario_id"] = scenario_id
            d["stage"] = stage
            d["created_at"] = now
            hist.insert(0, d)

    def list_solutions(self, scenario_id: str) -> list[dict]:
        return list(self._solutions.get(scenario_id, []))

    def list_pick_revisions(self, scenario_id: str) -> list[dict]:
        return list(reversed(self._pick_revisions.get(scenario_id, [])))


def create_store():
    url = os.environ.get("DATABASE_URL")
    if url:
        from .db.repo import SQLStore
        return SQLStore(url)
    return InMemoryStore()


store = create_store()
