"""FastAPI 应用入口。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_locate import router as locate_router
from .api.routes_picks import router as picks_router
from .api.routes_scenarios import router as scenarios_router
from .core.velocity_model import DEFAULT_MODEL, ENGINE_VERSION

app = FastAPI(
    title="地震定位教学演示",
    description=(
        "从台站波形到时恢复候选事件位置的教学应用。"
        "使用简化均匀半空间速度模型, 结果不构成真实地震预警。"
    ),
    version=ENGINE_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 教学演示; 生产部署应收紧
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scenarios_router)
app.include_router(picks_router)
app.include_router(locate_router)


@app.get("/api/velocity-model")
def velocity_model():
    """当前使用的简化速度模型及其版本与适用范围声明。"""
    return DEFAULT_MODEL.describe()


@app.get("/api/health")
def health():
    return {"status": "ok", "engine_version": ENGINE_VERSION,
            "model_version": DEFAULT_MODEL.version}
