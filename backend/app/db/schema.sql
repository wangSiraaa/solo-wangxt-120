-- PostgreSQL/PostGIS 权威模式 (docker 初始化用; 与应用内 db/migrate.py 幂等兼容)
-- 保存台站、raw/revised 两阶段拾取、修订历史与绑定版本的定位结果历史。

CREATE EXTENSION IF NOT EXISTS postgis;

-- 场景 (合成数据集), data_version 标识数据集版本
CREATE TABLE IF NOT EXISTS scenarios (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    teaching_points JSONB NOT NULL DEFAULT '[]',
    data_version    TEXT NOT NULL,
    true_source     JSONB NOT NULL,        -- 教学场景已知真值
    seed            INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 台站: 按场景区分 (合成数据集各自独立部署), geom 为 PostGIS 生成列
CREATE TABLE IF NOT EXISTS stations (
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    id          TEXT NOT NULL,
    name        TEXT NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    geom        GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS
                (ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scenario_id, id)
);

-- 到时拾取: stage 严格区分 raw (原始自动拾取, 只读) 与 revised (人工修订)
CREATE TABLE IF NOT EXISTS picks (
    id          BIGSERIAL PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    station_id  TEXT NOT NULL,
    stage       TEXT NOT NULL CHECK (stage IN ('raw', 'revised')),
    phase       TEXT NOT NULL CHECK (phase IN ('P', 'S')),  -- P/S 不可混用
    time_s      DOUBLE PRECISION NOT NULL,
    weight      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    author      TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scenario_id, station_id, stage, phase),
    FOREIGN KEY (scenario_id, station_id) REFERENCES stations(scenario_id, id)
);

-- raw 不可变: 数据库级触发器兜底 (应用层同样拒绝)
CREATE OR REPLACE FUNCTION picks_raw_immutable() RETURNS trigger AS $$
BEGIN
    IF OLD.stage = 'raw' THEN
        RAISE EXCEPTION 'raw 拾取不可修改或删除 (stage=raw)';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS picks_raw_immutable ON picks;
CREATE TRIGGER picks_raw_immutable
BEFORE UPDATE OR DELETE ON picks
FOR EACH ROW EXECUTE FUNCTION picks_raw_immutable();

-- 人工修订历史: 每次保存 revised 追加留痕
CREATE TABLE IF NOT EXISTS pick_revisions (
    id          BIGSERIAL PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    station_id  TEXT NOT NULL,
    phase       TEXT NOT NULL CHECK (phase IN ('P', 'S')),
    time_s      DOUBLE PRECISION NOT NULL,
    weight      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    author      TEXT,
    saved_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 定位结果历史: 每次定位运行追加一条, 绑定模型/引擎/数据版本
CREATE TABLE IF NOT EXISTS solutions (
    id                BIGSERIAL PRIMARY KEY,
    scenario_id       TEXT NOT NULL REFERENCES scenarios(id),
    stage             TEXT NOT NULL CHECK (stage IN ('raw', 'revised')),
    status            TEXT NOT NULL CHECK (status IN ('OK','POORLY_CONSTRAINED','UNLOCATABLE')),
    status_reasons    JSONB NOT NULL DEFAULT '[]',
    lat               DOUBLE PRECISION,
    lon               DOUBLE PRECISION,
    geom              GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS
                      (CASE WHEN lat IS NULL THEN NULL
                            ELSE ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography END) STORED,
    depth_km          DOUBLE PRECISION NOT NULL,   -- 固定深度, 非反演参数
    origin_time_s     DOUBLE PRECISION,
    rms_residual_s    DOUBLE PRECISION,
    azimuthal_gap_deg DOUBLE PRECISION,
    condition_number  DOUBLE PRECISION,
    ellipse_68        JSONB,
    alternate_minimum JSONB,
    residuals         JSONB NOT NULL DEFAULT '[]',  -- 逐台残差与离群标记
    n_stations        INTEGER NOT NULL DEFAULT 0,
    n_p_picks         INTEGER NOT NULL DEFAULT 0,
    n_s_picks         INTEGER NOT NULL DEFAULT 0,
    model_version     TEXT NOT NULL,
    engine_version    TEXT NOT NULL,
    data_version      TEXT NOT NULL,
    disclaimer        TEXT NOT NULL DEFAULT '教学演示结果, 不构成真实地震预警。',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 模式迁移版本记录
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_picks_scenario ON picks(scenario_id, stage);
CREATE INDEX IF NOT EXISTS idx_pick_revisions_scenario ON pick_revisions(scenario_id);
CREATE INDEX IF NOT EXISTS idx_solutions_scenario ON solutions(scenario_id, stage);
