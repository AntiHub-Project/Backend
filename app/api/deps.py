"""
API 依赖注入
提供数据库会话、Redis 客户端、认证等依赖
"""
from typing import AsyncGenerator, Optional
import logging
from fastapi import Depends, HTTPException, status, BackgroundTasks
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
from app.repositories.user_repository import UserRepository
from app.core.exceptions import (
    InvalidTokenError,
    TokenExpiredError,
    TokenBlacklistedError,
    UserNotFoundError,
    AccountDisabledError,
)

logger = logging.getLogger(__name__)

# API key 认证缓存 TTL（秒）
API_KEY_AUTH_CACHE_TTL = 60


async def update_api_key_last_used_background(api_key: str):
    """
    后台任务：更新 API key 最后使用时间
    
    注意：此函数在后台执行，失败不应影响主请求
    """
    try:
        from app.db.session import get_session_maker
        session_maker = get_session_maker()
        async with session_maker() as db:
            repo = APIKeyRepository(db)
            await repo.update_last_used(api_key)
            await db.commit()
            logger.debug(f"后台更新 API key 使用时间成功: {api_key[:10]}...")
    except Exception as e:
        # 后台任务失败不应影响主流程，仅记录警告
        logger.warning(f"后台更新 API key 使用时间失败: {e}")


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
    db: AsyncSession = Depends(get_db_session),
    redis: RedisClient = Depends(get_redis)
) -> PluginAPIService:
    """
    获取Plug-in API服务
    
    Returns:
        PluginAPIService: Plug-in API服务实例
    """
    return PluginAPIService(db, redis)


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
        logger.warning(f"令牌验证失败: {type(e).__name__}: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except UserNotFoundError as e:
        logger.warning(f"用户不存在: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except AccountDisabledError as e:
        logger.warning(f"账号已禁用: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message,
        )
    except Exception as e:
        logger.error(f"认证过程发生未预期错误: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"认证服务异常: {type(e).__name__}",
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
    db: AsyncSession = Depends(get_db_session),
    redis: RedisClient = Depends(get_redis),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> User:
    """
    通过API key获取用户
    用于OpenAI兼容的API端点
    
    优化：
    1. 使用 Redis 缓存认证结果
    2. update_last_used 改为后台任务
    
    Args:
        credentials: HTTP Authorization 凭证
        db: 数据库会话
        redis: Redis 客户端
        background_tasks: 后台任务
        
    Returns:
        User: 用户对象
        
    Raises:
        HTTPException: 认证失败时抛出 401 错误
    """
    try:
        # 提取API key
        api_key = credentials.credentials
        
        cache_key = f"api_key_auth:{api_key}"
        
        # 1. 尝试从 Redis 缓存获取
        try:
            cached_data = await redis.get_json(cache_key)
            if cached_data:
                logger.debug(f"从缓存获取 API key 认证结果: {api_key[:10]}...")
                # 从缓存重建 User 对象
                user = User(
                    id=cached_data["id"],
                    username=cached_data["username"],
                    is_active=cached_data["is_active"],
                    beta=cached_data.get("beta", 0)
                )
                user._config_type = cached_data.get("_config_type")
                
                # 后台更新 last_used（不阻塞）
                background_tasks.add_task(update_api_key_last_used_background, api_key)
                
                return user
        except Exception as e:
            logger.warning(f"Redis 缓存读取失败: {e}")
        
        # 2. 缓存未命中，查询数据库
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
        
        # 获取用户
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(key_record.user_id)
        
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
        user._config_type = key_record.config_type
        
        # 3. 存入缓存
        try:
            user_data = {
                "id": user.id,
                "username": user.username,
                "is_active": user.is_active,
                "beta": user.beta,
                "_config_type": key_record.config_type
            }
            await redis.set_json(cache_key, user_data, expire=API_KEY_AUTH_CACHE_TTL)
            logger.debug(f"API key 认证结果已缓存: {api_key[:10]}..., TTL={API_KEY_AUTH_CACHE_TTL}s")
        except Exception as e:
            logger.warning(f"Redis 缓存写入失败: {e}")
        
        # 4. 后台更新 last_used
        background_tasks.add_task(update_api_key_last_used_background, api_key)
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"API密钥认证失败",
            headers={"WWW-Authenticate": "Bearer"},
        )