"""模式初始化 / 迁移。

migrate(engine) 幂等:
1. metadata.create_all 建立核心表 (PostgreSQL / SQLite 均可);
2. PostgreSQL 上追加 PostGIS 相关对象 (扩展、geography 生成列、
   raw 不可变触发器) —— 与 db/schema.sql 中的权威定义一致;
3. schema_migrations 记录已应用版本。

docker 部署时 db 容器也会执行 schema.sql 初始化, 两者幂等兼容。
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import Base, SchemaMigrationRow
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# PostgreSQL 专有: PostGIS geography 生成列 + raw 拾取不可变触发器
PG_EXTRAS = [
    "CREATE EXTENSION IF NOT EXISTS postgis",
    """
    ALTER TABLE stations
      ADD COLUMN IF NOT EXISTS geom geography(POINT, 4326)
      GENERATED ALWAYS AS
        (ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography) STORED
    """,
    """
    ALTER TABLE solutions
      ADD COLUMN IF NOT EXISTS geom geography(POINT, 4326)
      GENERATED ALWAYS AS
        (CASE WHEN lat IS NULL THEN NULL
              ELSE ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography END) STORED
    """,
    """
    CREATE OR REPLACE FUNCTION picks_raw_immutable() RETURNS trigger AS $$
    BEGIN
        IF OLD.stage = 'raw' THEN
            RAISE EXCEPTION 'raw 拾取不可修改或删除 (stage=raw)';
        END IF;
        RETURN COALESCE(NEW, OLD);
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS picks_raw_immutable ON picks",
    """
    CREATE TRIGGER picks_raw_immutable
    BEFORE UPDATE OR DELETE ON picks
    FOR EACH ROW EXECUTE FUNCTION picks_raw_immutable()
    """,
]


def migrate(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    is_pg = engine.dialect.name == "postgresql"
    with Session(engine) as s:
        applied = {r.version for r in s.query(SchemaMigrationRow).all()}
        if SCHEMA_VERSION in applied:
            return
        if is_pg:
            for stmt in PG_EXTRAS:
                try:
                    s.execute(text(stmt))
                    s.commit()
                except Exception as exc:  # PostGIS 缺失等: 降级为核心关系链
                    s.rollback()
                    log.warning("PostGIS 扩展步骤跳过 (%s): %s",
                                stmt.strip().splitlines()[0][:50], exc)
        s.add(SchemaMigrationRow(version=SCHEMA_VERSION,
                                 description="initial schema"))
        s.commit()
