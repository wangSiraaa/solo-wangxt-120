"""人工修订拾取路由。raw (原始自动拾取) 只读, revised (人工修订) 可写并留痕。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core.locate import Pick
from ..core.velocity_model import DEFAULT_MODEL
from ..schemas import PickOut, PicksUpdate
from ..store import store

router = APIRouter(prefix="/api/scenarios/{scenario_id}/picks", tags=["picks"])


@router.get("", response_model=dict[str, list[PickOut]])
def get_picks(scenario_id: str):
    sc = store.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")
    return {
        "raw": [PickOut(**p.__dict__, stage="raw") for p in sc.raw_picks],
        "revised": [PickOut(**p.__dict__, stage="revised") for p in sc.revised_picks],
    }


@router.put("/revised", response_model=list[PickOut])
def put_revised_picks(scenario_id: str, body: PicksUpdate):
    """保存人工修订 (持久化 + 追加修订历史)。raw 拾取不受此接口影响。"""
    sc = store.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")
    # 校验: 台站存在且震相合法 (P/S 严格区分)
    for p in body.picks:
        if p.station_id not in sc.stations:
            raise HTTPException(400, f"未知台站 {p.station_id!r}")
        DEFAULT_MODEL.velocity_for_phase(p.phase)  # 非法震相 -> 400
    picks = [Pick(p.station_id, p.phase.upper(), p.time_s, p.weight) for p in body.picks]
    store.update_revised_picks(scenario_id, picks, author=body.author)
    return [PickOut(**p.__dict__, stage="revised") for p in picks]


@router.get("/revisions", response_model=list[dict])
def get_pick_revisions(scenario_id: str):
    """人工修订历史 (追加式, 新→旧)。"""
    if store.get(scenario_id) is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")
    return store.list_pick_revisions(scenario_id)
