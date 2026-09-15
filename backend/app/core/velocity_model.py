"""简化速度模型 —— 仅用于教学演示。

模型假设（必须在所有展示结果中明确声明）:
- 均匀半空间, 平直地球, 直射线近似
- 深度固定 (不作为反演参数)
- P 波与 S 波使用各自独立的速度, 任何情况下不得混用

模型版本号会绑定到每一次定位结果上, 便于重算与解释。
"""
from __future__ import annotations

from dataclasses import dataclass

MODEL_VERSION = "homogeneous-halfspace-v1"
ENGINE_VERSION = "locate-engine-1.0.0"


@dataclass(frozen=True)
class VelocityModel:
    version: str
    vp_km_s: float
    vs_km_s: float
    fixed_depth_km: float

    def velocity_for_phase(self, phase: str) -> float:
        """按震相返回速度。P/S 严格分离, 未知震相直接报错而不是猜测。"""
        p = phase.strip().upper()
        if p == "P":
            return self.vp_km_s
        if p == "S":
            return self.vs_km_s
        raise ValueError(f"未知震相 {phase!r}: 仅支持 'P' 或 'S', 不允许混用速度")

    def describe(self) -> dict:
        return {
            "version": self.version,
            "type": "均匀半空间 / 平直地球 / 直射线 (教学简化模型)",
            "vp_km_s": self.vp_km_s,
            "vs_km_s": self.vs_km_s,
            "vp_vs_ratio": round(self.vp_km_s / self.vs_km_s, 4),
            "fixed_depth_km": self.fixed_depth_km,
            "caveats": [
                "真实地壳速度随深度变化, 本模型仅为教学简化",
                "深度固定, 不参与反演",
                "结果不构成真实地震预警",
            ],
        }


DEFAULT_MODEL = VelocityModel(
    version=MODEL_VERSION,
    vp_km_s=5.8,
    vs_km_s=5.8 / 1.73,
    fixed_depth_km=10.0,
)
