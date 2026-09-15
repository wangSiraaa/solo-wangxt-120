-- PostgreSQL/PostGIS 持久化模式
-- 教学演示默认使用内存存储 (app/store.py); 本模式用于生产部署,
-- 保存台站、两阶段拾取与绑定模型/数据版本的定位结果。

CREATE EXTENSION IF NOT EXISTS postgis;

-- 台站 (地理位置用 PostGIS geography 类型)
CREATE TABLE IF NOT EXISTS stations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    geom        GEOGRAPHY(POINT, 4326) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 场景 (合成数据集), data_version 标识数据集版本
CREATE TABLE IF NOT EXISTS scenarios (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    data_version  TEXT NOT NULL,
    true_source   JSONB NOT NULL,        -- 教学场景已知真值
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 到时拾取: stage 严格区分 raw (原始自动拾取, 只读) 与 revised (人工修订)
CREATE TABLE IF NOT EXISTS picks (
    id          BIGSERIAL PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    station_id  TEXT NOT NULL REFERENCES stations(id),
    stage       TEXT NOT NULL CHECK (stage IN ('raw', 'revised')),
    phase       TEXT NOT NULL CHECK (phase IN ('P', 'S')),  -- P/S 不可混用
    time_s      DOUBLE PRECISION NOT NULL,
    weight      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    author      TEXT,                     -- 修订人 (教学署名)
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scenario_id, station_id, stage, phase)
);

-- 定位结果: 绑定速度模型版本、引擎版本与数据版本, 重算可解释
CREATE TABLE IF NOT EXISTS solutions (
    id               BIGSERIAL PRIMARY KEY,
    scenario_id      TEXT NOT NULL REFERENCES scenarios(id),
    stage            TEXT NOT NULL CHECK (stage IN ('raw', 'revised')),
    status           TEXT NOT NULL CHECK (status IN ('OK','POORLY_CONSTRAINED','UNLOCATABLE')),
    status_reasons   JSONB NOT NULL DEFAULT '[]',
    geom             GEOGRAPHY(POINT, 4326),          -- UNLOCATABLE 时可为空
    depth_km         DOUBLE PRECISION NOT NULL,        -- 固定深度, 非反演参数
    origin_time_s    DOUBLE PRECISION,
    rms_residual_s   DOUBLE PRECISION,
    azimuthal_gap_deg DOUBLE PRECISION,
    ellipse_68       JSONB,
    residuals        JSONB NOT NULL,                   -- 逐台残差与离群标记
    model_version    TEXT NOT NULL,
    engine_version   TEXT NOT NULL,
    data_version     TEXT NOT NULL,
    disclaimer       TEXT NOT NULL DEFAULT '教学演示结果, 不构成真实地震预警。',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_picks_scenario ON picks(scenario_id, stage);
CREATE INDEX IF NOT EXISTS idx_solutions_scenario ON solutions(scenario_id, stage);
