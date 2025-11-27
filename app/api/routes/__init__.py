"""
API 路由模块
"""
from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.plugin_api import router as plugin_api_router
from app.api.routes.api_keys import router as api_keys_router
from app.api.routes.v1 import router as v1_router
from app.api.routes.usage import router as usage_router
from app.api.routes.kiro import router as kiro_router

__all__ = [
    "auth_router",
    "health_router",
    "plugin_api_router",
    "api_keys_router",
    "v1_router",
    "usage_router",
    "kiro_router",
]