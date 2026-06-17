"""计算机视觉基础设施。"""
from src.infrastructure.cv.matcher import (
    MultiScaleTemplateMatcher,
    ResolutionAdapter,
    RingSampler,
    RingSample,
)

__all__ = [
    "MultiScaleTemplateMatcher",
    "ResolutionAdapter",
    "RingSampler",
    "RingSample",
]
