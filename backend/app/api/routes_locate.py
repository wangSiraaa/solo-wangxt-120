"""定位路由: 对 raw 与 revised 两阶段到时分别定位, 返回可比较的候选解。"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ..core.locate import locate
from ..core.velocity_model import DEFAULT_MODEL
from ..schemas import LocateResponse, LocationResultOut
from ..store import store

router = APIRouter(prefix="/api/scenarios/{scenario_id}/locate", tags=["locate"])


@router.post("", response_model=LocateResponse)
def run_locate(scenario_id: str):
    """对场景当前的两组到时 (raw / revised) 分别定位。

    返回的每个候选解都绑定速度模型版本与数据版本, 重算结果可解释、可复现。
    """
    sc = store.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")

    results: dict[str, LocationResultOut] = {}
    for stage, picks in (("raw", sc.raw_picks), ("revised", sc.revised_picks)):
        if not picks:
            continue
        res = locate(picks, sc.stations, DEFAULT_MODEL)
        results[stage] = LocationResultOut(stage=stage, **asdict(res))

    return LocateResponse(
        scenario_id=scenario_id,
        results=results,
        model=DEFAULT_MODEL.describe(),
        data_version=store.data_version,
    )
