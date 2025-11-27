"""
API 依赖注入
提供数据库会话、Redis 客户端、认证等依赖
"""
from typing import AsyncGenerator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.cache import get_redis_client, RedisClient
from app.services.auth_service import AuthService
from app.services.oauth_service import OAuthService
from app.services.github_oauth_service import GitHubOAuthService
from app.services.user_service import UserService
from app.services.plugin_api_service import PluginAPIService
from app.models.user import User
from app.repositories.api_key_repository import APIKeyRepository
from app.core.exceptions import (
    InvalidTokenError,
    TokenExpiredError,
    TokenBlacklistedError,
    UserNotFoundError,
    AccountDisabledError,
)


# HTTP Bearer 认证方案
security = HTTPBearer()


# ==================== 数据库依赖 ====================

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话
    
    Yields:
        AsyncSession: 数据库会话
    """
    async for session in get_db():
        yield session


# ==================== Redis 依赖 ====================

async def get_redis() -> RedisClient:
    """
    获取 Redis 客户端
    
    Returns:
        RedisClient: Redis 客户端实例
    """
    return get_redis_client()


# ==================== 服务依赖 ====================

async def get_auth_service(
    db: AsyncSession = Depends(get_db_session),
    redis: RedisClient = Depends(get_redis)
) -> AuthService:
    """
    获取认证服务
    
    Returns:
        AuthService: 认证服务实例
    """
    return AuthService(db, redis)


async def get_oauth_service(
    db: AsyncSession = Depends(get_db_session),
    redis: RedisClient = Depends(get_redis)
) -> OAuthService:
    """
    获取 OAuth 服务
    
    Returns:
        OAuthService: OAuth 服务实例
    """
    return OAuthService(db, redis)


async def get_github_oauth_service(
    db: AsyncSession = Depends(get_db_session),
    redis: RedisClient = Depends(get_redis)
) -> GitHubOAuthService:
    """
    获取 GitHub OAuth 服务
    
    Returns:
        GitHubOAuthService: GitHub OAuth 服务实例
    """
    return GitHubOAuthService(db, redis)


async def get_user_service(
    db: AsyncSession = Depends(get_db_session)
) -> UserService:
    """
    获取用户服务
    
    Returns:
        UserService: 用户服务实例
    """
    return UserService(db)


async def get_plugin_api_service(
    db: AsyncSession = Depends(get_db_session)
) -> PluginAPIService:
    """
    获取Plug-in API服务
    
    Returns:
        PluginAPIService: Plug-in API服务实例
    """
    return PluginAPIService(db)


# ==================== 认证依赖 ====================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth_service: AuthService = Depends(get_auth_service)
) -> User:
    """
    获取当前登录用户
    从请求头提取和验证 JWT 令牌
    
    Args:
        credentials: HTTP Authorization 凭证
        auth_service: 认证服务
        
    Returns:
        User: 当前用户对象
        
    Raises:
        HTTPException: 认证失败时抛出 401 错误
    """
    try:
        # 提取令牌
        token = credentials.credentials
        
        # 获取当前用户
        user = await auth_service.get_current_user(token)
        
        return user
        
    except (InvalidTokenError, TokenExpiredError, TokenBlacklistedError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except UserNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except AccountDisabledError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    auth_service: AuthService = Depends(get_auth_service)
) -> Optional[User]:
    """
    获取当前登录用户(可选)
    令牌无效时返回 None 而不是抛出异常
    
    Args:
        credentials: HTTP Authorization 凭证
        auth_service: 认证服务
        
    Returns:
        User 对象或 None
    """
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        user = await auth_service.get_current_user(token)
        return user
    except Exception:
        return None


async def get_user_from_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db_session)
) -> User:
    """
    通过API key获取用户
    用于OpenAI兼容的API端点
    
    Args:
        credentials: HTTP Authorization 凭证
        db: 数据库会话
        
    Returns:
        User: 用户对象
        
    Raises:
        HTTPException: 认证失败时抛出 401 错误
    """
    try:
        # 提取API key
        api_key = credentials.credentials
        
        # 查询API key
        repo = APIKeyRepository(db)
        key_record = await repo.get_by_key(api_key)
        
        if not key_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的API密钥",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not key_record.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API密钥已被禁用",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 更新最后使用时间
        await repo.update_last_used(api_key)
        await db.commit()
        
        # 获取用户
        user_service = UserService(db)
        user = await user_service.get_user_by_id(key_record.user_id)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户账号已被禁用"
            )
        
        # 将config_type附加到user对象上，供路由使用
        print(f"🔍 [deps.py] API Key ID: {key_record.id}, User ID: {key_record.user_id}, Config Type from DB: {key_record.config_type}")
        user._config_type = key_record.config_type
        print(f"🔍 [deps.py] Set user._config_type to: {user._config_type}")
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"API密钥认证失败",
            headers={"WWW-Authenticate": "Bearer"},
        )