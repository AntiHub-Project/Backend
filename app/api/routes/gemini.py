"""
Gemini兼容的API端点
支持Gemini API格式的图片生成 (/v1beta/models/{model}:generateContent)
支持图生图功能和SSE流式响应（每20秒心跳保活）
"""
from typing import Optional
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps_flexible import get_user_flexible_with_goog_api_key
from app.api.deps import get_plugin_api_service
from app.models.user import User
from app.services.plugin_api_service import PluginAPIService
from app.schemas.plugin_api import GenerateContentRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1beta", tags=["Gemini兼容API"])


@router.post(
    "/models/{model}:generateContent",
    summary="图片生成",
    description="使用Gemini模型生成图片，支持文生图和图生图。支持JWT token、Bearer API key或x-goog-api-key标头认证。响应使用SSE格式（心跳保活）"
)
async def generate_content(
    model: str,
    request: GenerateContentRequest,
    current_user: User = Depends(get_user_flexible_with_goog_api_key),
    service: PluginAPIService = Depends(get_plugin_api_service)
):
    try:
        # 获取 config_type（通过 API key 认证时会设置）
        config_type = getattr(current_user, '_config_type', None)
        
        # 使用流式请求以支持SSE心跳保活
        async def generate():
            async for chunk in service.generate_content_stream(
                user_id=current_user.id,
                model=model,
                request_data=request.model_dump(),
                config_type=config_type
            ):
                yield chunk
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except httpx.HTTPStatusError as e:
        # 透传上游API的错误响应
        error_data = getattr(e, 'response_data', {"detail": str(e)})
        if isinstance(error_data, dict) and 'detail' in error_data:
            detail = error_data['detail']
        else:
            detail = error_data
        raise HTTPException(
            status_code=e.response.status_code,
            detail=detail
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"图片生成失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"图片生成失败: {str(e)}"
        )

@router.post(
    "/models/{model}:streamGenerateContent",
    summary="图片生成（流式）",
    description="使用Gemini模型生成图片，支持文生图和图生图。支持JWT token、Bearer API key或x-goog-api-key标头认证。响应使用SSE格式（心跳保活）。使用 ?alt=sse 查询参数启用SSE流式响应。"
)
async def stream_generate_content(
    model: str,
    request: GenerateContentRequest,
    alt: str = Query(default="sse", description="响应格式，默认为sse"),
    current_user: User = Depends(get_user_flexible_with_goog_api_key),
    service: PluginAPIService = Depends(get_plugin_api_service)
):
    try:
        # 获取 config_type（通过 API key 认证时会设置）
        config_type = getattr(current_user, '_config_type', None)
        
        # 使用流式请求以支持SSE心跳保活
        async def generate():
            async for chunk in service.generate_content_stream(
                user_id=current_user.id,
                model=model,
                request_data=request.model_dump(),
                config_type=config_type
            ):
                yield chunk
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except httpx.HTTPStatusError as e:
        # 透传上游API的错误响应
        error_data = getattr(e, 'response_data', {"detail": str(e)})
        if isinstance(error_data, dict) and 'detail' in error_data:
            detail = error_data['detail']
        else:
            detail = error_data
        raise HTTPException(
            status_code=e.response.status_code,
            detail=detail
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"图片生成失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"图片生成失败: {str(e)}"
        )