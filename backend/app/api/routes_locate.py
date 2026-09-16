"""定位路由: 对 raw 与 revised 两阶段到时分别定位, 持久化结果历史。"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ..core.locate import locate
from ..core.velocity_model import DEFAULT_MODEL
from ..schemas import LocateResponse, LocationResultOut, SolutionHistoryOut
from ..store import store

router = APIRouter(prefix="/api/scenarios/{scenario_id}/locate", tags=["locate"])


@router.post("", response_model=LocateResponse)
def run_locate(scenario_id: str):
    """对场景当前的两组到时 (raw / revised) 分别定位并持久化结果。

    每个候选解绑定速度模型版本、引擎版本与数据指纹, 写入结果历史,
    重算可解释、可复现; 历史可通过 GET .../locate/history 读回。
    """
    sc = store.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")

    domain_results = {}
    results: dict[str, LocationResultOut] = {}
    for stage, picks in (("raw", sc.raw_picks), ("revised", sc.revised_picks)):
        if not picks:
            continue
        res = locate(picks, sc.stations, DEFAULT_MODEL)
        domain_results[stage] = res
        results[stage] = LocationResultOut(stage=stage, **asdict(res))

    store.save_solutions(scenario_id, domain_results)  # 持久化历史

    return LocateResponse(
        scenario_id=scenario_id,
        results=results,
        model=DEFAULT_MODEL.describe(),
        data_version=store.data_version,
    )


@router.get("/history", response_model=list[SolutionHistoryOut])
def locate_history(scenario_id: str):
    """历史定位结果 (新→旧), 每条绑定模型/引擎/数据版本。"""
    if store.get(scenario_id) is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")
    return store.list_solutions(scenario_id)
