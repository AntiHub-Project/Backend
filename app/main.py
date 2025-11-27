"""
FastAPI 应用主文件
应用入口点和配置
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.exceptions import BaseAPIException
from app.db.session import init_db, close_db
from app.cache import init_redis, close_redis
from app.api.routes import (
    auth_router,
    health_router,
    plugin_api_router,
    api_keys_router,
    v1_router,
    usage_router,
    kiro_router
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# ==================== 生命周期事件 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    启动和关闭事件处理
    """
    # 启动事件
    settings = get_settings()
    
    # 初始化数据库连接
    try:
        await init_db()
    except Exception as e:
        raise
    
    # 初始化 Redis 连接
    try:
        await init_redis()
    except Exception as e:
        raise
    
    yield
    
    # 关闭事件
    # 关闭数据库连接
    try:
        await close_db()
    except Exception as e:
        pass
    
    # 关闭 Redis 连接
    try:
        await close_redis()
    except Exception as e:
        pass


# ==================== 创建 FastAPI 应用 ====================

def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用
    
    Returns:
        配置好的 FastAPI 应用实例
    """
    settings = get_settings()
    
    # 创建 FastAPI 应用
    # 生产环境禁用API文档
    docs_url = "/api/docs" if settings.is_development else None
    redoc_url = "/api/redoc" if settings.is_development else None
    openapi_url = "/api/openapi.json" if settings.is_development else None
    
    app = FastAPI(
        title="共享账号管理系统",
        description="基于 FastAPI 的共享账号管理系统,支持传统登录和 OAuth SSO",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url
    )
    
    # ==================== CORS 配置 ====================
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应该配置具体的域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # ==================== 注册路由 ====================
    
    app.include_router(auth_router, prefix="/api")
    app.include_router(health_router, prefix="/api")
    app.include_router(plugin_api_router, prefix="/api")
    app.include_router(api_keys_router, prefix="/api")
    app.include_router(usage_router, prefix="/api")
    app.include_router(kiro_router)  # Kiro账号管理API (Beta)
    app.include_router(v1_router)  # OpenAI兼容API，支持Antigravity和Kiro配置
    
    # ==================== 异常处理器 ====================
    
    @app.exception_handler(BaseAPIException)
    async def api_exception_handler(request: Request, exc: BaseAPIException):
        """处理自定义 API 异常"""
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict()
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理数据验证异常"""
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error_code": "VALIDATION_ERROR",
                "message": "数据验证失败",
                "details": exc.errors()
            }
        )
    
    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(request: Request, exc: SQLAlchemyError):
        """处理数据库异常"""
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "DATABASE_ERROR",
                "message": "数据库操作失败",
                "details": {"error": str(exc)}
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理通用异常"""
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "服务器内部错误",
                "details": {"error": str(exc)}
            }
        )
    
    # ==================== 根路径 ====================
    
    @app.get("/", tags=["根路径"])
    async def root():
        """根路径欢迎信息"""
        return {
            "message": "200",
        }
    
    return app


# 创建应用实例
app = create_app()


# ==================== 开发服务器 ====================

if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level=settings.log_level.lower()
    )