"""场景存储。

默认使用内存存储 (合成场景在启动时生成), 便于教学演示与测试。
PostgreSQL/PostGIS 持久化见 db/schema.sql 与 docker-compose.yml;
生产部署时可将本模块替换为 SQLAlchemy 实现, API 层无需改动。
"""
from __future__ import annotations

from .core.locate import Pick
from .core.synthetic import SCENARIO_DATA_VERSION, Scenario, build_scenarios
from .core.velocity_model import DEFAULT_MODEL


class ScenarioStore:
    def __init__(self):
        self._scenarios: dict[str, Scenario] = build_scenarios(DEFAULT_MODEL)
        self.data_version = SCENARIO_DATA_VERSION

    def list(self) -> list[Scenario]:
        return list(self._scenarios.values())

    def get(self, scenario_id: str) -> Scenario | None:
        return self._scenarios.get(scenario_id)

    def update_revised_picks(self, scenario_id: str, picks: list[Pick]) -> Scenario | None:
        """保存人工修订到时。raw 永不被修改 —— 两阶段严格分离。"""
        sc = self._scenarios.get(scenario_id)
        if sc is None:
            return None
        sc.revised_picks = picks
        return sc


store = ScenarioStore()
