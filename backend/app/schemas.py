"""Pydantic 模式: API 请求/响应。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StationOut(BaseModel):
    id: str
    name: str
    lat: float
    lon: float


class PickIn(BaseModel):
    station_id: str
    phase: str = Field(pattern="^[PpSs]$", description="仅允许 P 或 S, 不允许混用")
    time_s: float
    weight: float = 1.0


class PickOut(PickIn):
    stage: str  # "raw" | "revised"


class PicksUpdate(BaseModel):
    picks: list[PickIn]


class ScenarioSummary(BaseModel):
    id: str
    title: str
    description: str
    teaching_points: list[str]
    n_stations: int
    data_version: str


class ScenarioDetail(ScenarioSummary):
    stations: list[StationOut]
    raw_picks: list[PickOut]
    revised_picks: list[PickOut]
    true_source: dict  # 教学场景: 真值公开, 用于对比验证


class WaveformOut(BaseModel):
    station_id: str
    sample_rate: float
    t: list[float]
    y: list[float]


class PickResidualOut(BaseModel):
    station_id: str
    phase: str
    observed_s: float
    predicted_s: float
    residual_s: float
    is_outlier: bool


class LocationResultOut(BaseModel):
    stage: str
    status: str
    status_reasons: list[str]
    lat: float | None
    lon: float | None
    depth_km: float
    origin_time_s: float | None
    rms_residual_s: float | None
    residuals: list[PickResidualOut]
    azimuthal_gap_deg: float | None
    condition_number: float | None
    ellipse_68: dict | None
    alternate_minimum: dict | None
    n_stations: int
    n_p_picks: int
    n_s_picks: int
    model_version: str
    engine_version: str
    data_version: str
    disclaimer: str


class LocateResponse(BaseModel):
    scenario_id: str
    results: dict[str, LocationResultOut]  # 键: "raw" / "revised", 便于并排比较
    model: dict
    data_version: str
