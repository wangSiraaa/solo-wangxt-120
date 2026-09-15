"""场景与波形路由。"""
from __future__ import annotations

import io

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from obspy import Stream

from ..schemas import PickOut, ScenarioDetail, ScenarioSummary, StationOut, WaveformOut
from ..store import store
from ..core.synthetic import to_obspy_trace

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _summary(sc) -> ScenarioSummary:
    return ScenarioSummary(
        id=sc.id, title=sc.title, description=sc.description,
        teaching_points=sc.teaching_points, n_stations=len(sc.stations),
        data_version=store.data_version,
    )


@router.get("", response_model=list[ScenarioSummary])
def list_scenarios():
    return [_summary(sc) for sc in store.list()]


@router.get("/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(scenario_id: str):
    sc = store.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")
    s = _summary(sc)
    return ScenarioDetail(
        **s.model_dump(),
        stations=[StationOut(id=x.id, name=x.name, lat=x.lat, lon=x.lon)
                  for x in sc.stations.values()],
        raw_picks=[PickOut(**p.__dict__, stage="raw") for p in sc.raw_picks],
        revised_picks=[PickOut(**p.__dict__, stage="revised") for p in sc.revised_picks],
        true_source=sc.source,
    )


@router.get("/{scenario_id}/waveforms", response_model=list[WaveformOut])
def get_waveforms(scenario_id: str, decimate: int = 2):
    """JSON 波形 (默认 2 倍抽稀供前端绘图)。"""
    sc = store.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")
    if decimate < 1:
        raise HTTPException(400, "decimate 必须 >= 1")
    out = []
    for sta_id, (t, y) in sc.waveforms().items():
        out.append(WaveformOut(
            station_id=sta_id,
            sample_rate=50.0 / decimate,
            t=np.round(t[::decimate], 4).tolist(),
            y=np.round(y[::decimate], 5).tolist(),
        ))
    return out


@router.get("/{scenario_id}/waveforms.mseed")
def get_waveforms_mseed(scenario_id: str):
    """MiniSEED 下载 (ObsPy 写出), 供学生用标准工具复查波形。"""
    sc = store.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")
    st = Stream([to_obspy_trace(y, sta_id) for sta_id, (_, y) in sc.waveforms().items()])
    buf = io.BytesIO()
    st.write(buf, format="MSEED")
    return Response(
        content=buf.getvalue(), media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={scenario_id}.mseed"},
    )
