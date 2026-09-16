"""场景与波形路由。波形一律经 MiniSEED 示例文件由 obspy.read 解析得到。"""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..core import sample_data
from ..schemas import (
    PickOut, SampleDataOut, ScenarioDetail, ScenarioSummary, StationOut, WaveformOut,
)
from ..store import store

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _summary(sc) -> ScenarioSummary:
    return ScenarioSummary(
        id=sc.id, title=sc.title, description=sc.description,
        teaching_points=sc.teaching_points, n_stations=len(sc.stations),
        data_version=store.data_version,
    )


def _get_or_404(scenario_id: str):
    sc = store.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"场景 {scenario_id!r} 不存在")
    return sc


@router.get("", response_model=list[ScenarioSummary])
def list_scenarios():
    return [_summary(sc) for sc in store.list()]


@router.get("/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(scenario_id: str):
    sc = _get_or_404(scenario_id)
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
    """JSON 波形 (默认 2 倍抽稀): 由 MiniSEED 示例文件经 obspy.read 解析。"""
    _get_or_404(scenario_id)
    if decimate < 1:
        raise HTTPException(400, "decimate 必须 >= 1")
    try:
        parsed = sample_data.parse_waveforms(scenario_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return [
        WaveformOut(
            station_id=sta_id,
            sample_rate=round(1.0 / (t[1] - t[0]) / decimate, 4) if len(t) > 1 else 0,
            t=np.round(t[::decimate], 4).tolist(),
            y=np.round(y[::decimate], 5).tolist(),
        )
        for sta_id, (t, y) in parsed.items()
    ]


@router.get("/{scenario_id}/sample-data", response_model=SampleDataOut)
def get_sample_data(scenario_id: str, decimate: int = 5):
    """示例数据解析入口: MiniSEED 波形 + StationXML 台站元数据, 均由 ObsPy 解析。"""
    _get_or_404(scenario_id)
    try:
        parsed = sample_data.parse_waveforms(scenario_id)
        stations = sample_data.parse_stations(scenario_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return SampleDataOut(
        scenario_id=scenario_id,
        files={
            "mseed": sample_data.mseed_path(scenario_id).name,
            "stationxml": sample_data.stationxml_path(scenario_id).name,
        },
        parsed_with=f"obspy.read / obspy.read_inventory",
        stations=stations,
        waveforms=[
            WaveformOut(
                station_id=sta_id,
                sample_rate=round(1.0 / (t[1] - t[0]) / decimate, 4) if len(t) > 1 else 0,
                t=np.round(t[::decimate], 4).tolist(),
                y=np.round(y[::decimate], 5).tolist(),
            )
            for sta_id, (t, y) in parsed.items()
        ],
    )


@router.get("/{scenario_id}/waveforms.mseed")
def get_waveforms_mseed(scenario_id: str):
    """MiniSEED 示例文件下载, 供学生用标准工具复查波形。"""
    _get_or_404(scenario_id)
    path = sample_data.mseed_path(scenario_id)
    if not path.exists():
        raise HTTPException(404, f"示例数据文件缺失: {path}")
    return FileResponse(path, media_type="application/octet-stream",
                        filename=f"{scenario_id}.mseed")
