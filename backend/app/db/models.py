"""SQLAlchemy 模型: 台站、场景、两阶段拾取、修订历史、定位结果历史。

设计要点:
- 方言可移植 (PostgreSQL / SQLite), 便于测试与开发;
  PostgreSQL 部署时由 migrate.py 追加 PostGIS geography 生成列与
  raw 不可变触发器 (见 schema.sql 的等价定义)。
- picks.stage 严格区分 raw / revised; raw 行创建后不可改 (仓库层 + PG 触发器双重保证)。
- pick_revisions 为追加式修订历史; solutions 为追加式定位结果历史,
  每条绑定 model_version / engine_version / data_version。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, CheckConstraint, DateTime, Float, ForeignKey, ForeignKeyConstraint,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class StationRow(Base):
    """台站按场景区分 (合成教学数据集各自独立部署)。"""
    __tablename__ = "stations"
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    # PostgreSQL 部署时另有 geom GEOGRAPHY 生成列 (migrate.py / schema.sql)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScenarioRow(Base):
    __tablename__ = "scenarios"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    teaching_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    true_source: Mapped[dict] = mapped_column(JSON, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PickRow(Base):
    __tablename__ = "picks"
    __table_args__ = (
        CheckConstraint("stage IN ('raw','revised')", name="ck_picks_stage"),
        CheckConstraint("phase IN ('P','S')", name="ck_picks_phase"),
        ForeignKeyConstraint(["scenario_id", "station_id"],
                             ["stations.scenario_id", "stations.id"]),
        UniqueConstraint("scenario_id", "station_id", "stage", "phase",
                         name="uq_picks_scenario_station_stage_phase"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id"), nullable=False, index=True)
    station_id: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(8), nullable=False)
    phase: Mapped[str] = mapped_column(String(1), nullable=False)
    time_s: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PickRevisionRow(Base):
    """人工修订的追加式历史: 每次保存 revised 拾取都留痕。"""
    __tablename__ = "pick_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id"), nullable=False, index=True)
    station_id: Mapped[str] = mapped_column(String(32), nullable=False)
    phase: Mapped[str] = mapped_column(String(1), nullable=False)
    time_s: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SolutionRow(Base):
    """定位结果历史: 每次定位运行追加一条, 绑定模型/引擎/数据版本。"""
    __tablename__ = "solutions"
    __table_args__ = (
        CheckConstraint("stage IN ('raw','revised')", name="ck_solutions_stage"),
        CheckConstraint("status IN ('OK','POORLY_CONSTRAINED','UNLOCATABLE')",
                        name="ck_solutions_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    status_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_km: Mapped[float] = mapped_column(Float, nullable=False)
    origin_time_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    rms_residual_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    azimuthal_gap_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    ellipse_68: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    alternate_minimum: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    residuals: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    n_stations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_p_picks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_s_picks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SchemaMigrationRow(Base):
    __tablename__ = "schema_migrations"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(String(256), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
