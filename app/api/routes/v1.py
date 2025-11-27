"""
OpenAI兼容的API端点
支持API key或JWT token认证
根据API key的config_type自动选择Antigravity或Kiro配置
用户通过我们的key/token调用，我们再用plug-in key调用plug-in-api
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps_flexible import get_user_flexible
from app.api.deps import get_plugin_api_service, get_db_session
from app.models.user import User
from app.services.plugin_api_service import PluginAPIService
from app.services.kiro_service import KiroService
from app.schemas.plugin_api import ChatCompletionRequest


router = APIRouter(prefix="/v1", tags=["OpenAI兼容API"])

def get_kiro_service(db: AsyncSession = Depends(get_db_session)) -> KiroService:
    """获取Kiro服务实例"""
    return KiroService(db)


@router.get(
    "/models",
    summary="获取模型列表",
    description="获取可用的AI模型列表（OpenAI兼容）。根据API key的config_type自动选择Antigravity或Kiro配置"
)
async def list_models(
    current_user: User = Depends(get_user_flexible),
    antigravity_service: PluginAPIService = Depends(get_plugin_api_service),
    kiro_service: KiroService = Depends(get_kiro_service)
):
    """
    获取模型列表
    支持API key或JWT token认证
    
    **配置选择:**
    - 使用API key认证时，根据API key创建时选择的config_type自动选择配置
    - 使用JWT token认证时，默认使用Antigravity配置
    - Kiro配置需要beta权限
    """
    try:
        # 判断使用哪个服务
        # 如果用户有config_type属性（来自API key），使用该配置
        config_type = getattr(current_user, '_config_type', None)
        use_kiro = config_type == "kiro"
        
        if use_kiro:
            # 检查beta权限
            if current_user.beta != 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Kiro配置仅对beta计划用户开放"
                )
            result = await kiro_service.get_models(current_user.id)
        else:
            # 默认使用Antigravity，传递config_type
            result = await antigravity_service.get_models(current_user.id, config_type=config_type)
        
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取模型列表失败: {str(e)}"
        )


@router.post(
    "/chat/completions",
    summary="聊天补全",
    description="使用plug-in-api进行聊天补全（OpenAI兼容）。根据API key的config_type自动选择Antigravity或Kiro配置"
)
async def chat_completions(
    request: ChatCompletionRequest,
    current_user: User = Depends(get_user_flexible),
    antigravity_service: PluginAPIService = Depends(get_plugin_api_service),
    kiro_service: KiroService = Depends(get_kiro_service)
):
    """
    聊天补全
    支持两种认证方式：
    1. API key认证 - 用于程序调用，根据API key的config_type自动选择配置
    2. JWT token认证 - 用于网页聊天，默认使用Antigravity配置
    
    **配置选择:**
    - 使用API key时，根据创建时选择的config_type（antigravity/kiro）自动路由
    - 使用JWT token时，默认使用Antigravity配置
    - Kiro配置需要beta权限
    
    我们使用用户对应的plug-in key调用plug-in-api
    """
    try:
        # 判断使用哪个服务
        config_type = getattr(current_user, '_config_type', None)
        use_kiro = config_type == "kiro"
        
        if use_kiro:
            # 检查beta权限
            if current_user.beta != 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Kiro配置仅对beta计划用户开放"
                )
        
        # 准备额外的请求头
        extra_headers = {}
        if config_type:
            extra_headers["X-Account-Type"] = config_type
        
        # 如果是流式请求
        if request.stream:
            async def generate():
                if use_kiro:
                    async for chunk in kiro_service.chat_completions_stream(
                        user_id=current_user.id,
                        request_data=request.model_dump()
                    ):
                        yield chunk
                else:
                    async for chunk in antigravity_service.proxy_stream_request(
                        user_id=current_user.id,
                        method="POST",
                        path="/v1/chat/completions",
                        json_data=request.model_dump(),
                        extra_headers=extra_headers if extra_headers else None
                    ):
                        yield chunk
            
            return StreamingResponse(
                generate(),
                media_type="text/event-stream"
            )
        else:
            # 非流式请求
            if use_kiro:
                result = await kiro_service.chat_completions(
                    user_id=current_user.id,
                    request_data=request.model_dump()
                )
            else:
                result = await antigravity_service.proxy_request(
                    user_id=current_user.id,
                    method="POST",
                    path="/v1/chat/completions",
                    json_data=request.model_dump(),
                    extra_headers=extra_headers if extra_headers else None
                )
            return result
            
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"聊天补全失败: {str(e)}"
        )