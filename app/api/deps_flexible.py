"""
灵活的认证依赖
支持JWT token或API key两种认证方式
"""
import logging
from typing import Optional
from fastapi import Depends, HTTPException, status, Header, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.repositories.api_key_repository import APIKeyRepository
from app.repositories.user_repository import UserRepository
from app.api.deps import get_auth_service, get_redis
from app.cache import RedisClient, get_redis_client

logger = logging.getLogger(__name__)

# API key 认证缓存 TTL（秒）
API_KEY_AUTH_CACHE_TTL = 60


async def update_api_key_last_used_background(api_key: str):
    """
    后台任务：更新 API key 最后使用时间
    
    优化：使用 Redis 限流，避免频繁写入数据库
    """
    try:
        # 1. 检查 Redis 限流
        redis = get_redis_client()
        throttle_key = f"last_used_throttle:{api_key}"
        
        # 如果限流键存在，说明最近已更新过，跳过
        if await redis.exists(throttle_key):
            return
            
        # 2. 设置限流键 (60秒)
        await redis.set(throttle_key, "1", expire=60)
        
        # 3. 更新数据库
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


async def get_user_from_api_key_with_cache(
    api_key: str,
    db: AsyncSession,
    redis: RedisClient,
    background_tasks: BackgroundTasks
) -> User:
    """
    从缓存或数据库获取 API key 对应的用户
    
    优化策略：
    1. 优先从 Redis 缓存获取
    2. 缓存未命中时查询数据库
    3. 将结果缓存到 Redis（60秒）
    4. 后台更新 last_used 时间
    
    Args:
        api_key: API 密钥
        db: 数据库会话
        redis: Redis 客户端
        background_tasks: 后台任务
        
    Returns:
        User: 用户对象
        
    Raises:
        HTTPException: 认证失败
    """
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

security = HTTPBearer()


async def get_user_flexible(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
    redis: RedisClient = Depends(get_redis),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> User:
    """
    灵活认证：支持JWT token或API key
    
    - 如果token以'sk-'开头，视为API key
    - 否则视为JWT token
    
    优化：
    1. API key 认证使用 Redis 缓存
    2. update_last_used 改为后台任务
    
    Args:
        credentials: HTTP Authorization凭证
        db: 数据库会话
        auth_service: 认证服务
        redis: Redis 客户端
        background_tasks: 后台任务
        
    Returns:
        User: 用户对象
        
    Raises:
        HTTPException: 认证失败
    """
    token = credentials.credentials
    
    try:
        # 判断是API key还是JWT token
        if token.startswith('sk-'):
            # API key认证（使用缓存）
            return await get_user_from_api_key_with_cache(token, db, redis, background_tasks)
        else:
            # JWT token认证
            user = await auth_service.get_current_user(token)
            return user
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"认证失败: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_user_from_x_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> Optional[User]:
    """
    通过 X-Api-Key 标头获取用户
    用于 Anthropic 兼容的 API 端点
    
    优化：
    1. 使用 Redis 缓存认证结果
    2. update_last_used 改为后台任务
    
    Args:
        x_api_key: X-Api-Key 标头值
        db: 数据库会话
        redis: Redis 客户端
        background_tasks: 后台任务
        
    Returns:
        User: 用户对象，如果未提供 API key 则返回 None
        
    Raises:
        HTTPException: API key 无效或用户不存在时抛出错误
    """
    if not x_api_key:
        return None
    
    try:
        # 使用缓存认证
        return await get_user_from_api_key_with_cache(x_api_key, db, redis, background_tasks)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"API密钥认证失败: {str(e)}"
        )


async def get_user_flexible_with_x_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    x_api_key_user: Optional[User] = Depends(get_user_from_x_api_key),
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
    redis: RedisClient = Depends(get_redis),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> User:
    """
    灵活认证：支持 JWT token、Bearer API key 或 X-Api-Key 标头
    
    优先级：
    1. X-Api-Key 标头
    2. Authorization Bearer token (JWT 或 API key)
    
    优化：
    1. API key 认证使用 Redis 缓存
    2. update_last_used 改为后台任务
    
    Args:
        credentials: HTTP Authorization 凭证
        x_api_key_user: 通过 X-Api-Key 标头获取的用户
        db: 数据库会话
        auth_service: 认证服务
        redis: Redis 客户端
        background_tasks: 后台任务
        
    Returns:
        User: 用户对象
        
    Raises:
        HTTPException: 认证失败
    """
    # 优先使用 X-Api-Key 标头
    if x_api_key_user:
        return x_api_key_user
    
    # 如果没有 X-Api-Key，检查 Authorization 标头
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要提供认证凭证（X-Api-Key 标头或 Authorization Bearer token）",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    try:
        # 判断是 API key 还是 JWT token
        if token.startswith('sk-'):
            # API key 认证（使用缓存）
            return await get_user_from_api_key_with_cache(token, db, redis, background_tasks)
        else:
            # JWT token 认证
            user = await auth_service.get_current_user(token)
            return user
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"认证失败: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_user_from_goog_api_key(
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key"),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> Optional[User]:
    """
    通过 x-goog-api-key 标头获取用户
    用于 Gemini 兼容的 API 端点
    
    优化：
    1. 使用 Redis 缓存认证结果
    2. update_last_used 改为后台任务
    
    Args:
        x_goog_api_key: x-goog-api-key 标头值
        db: 数据库会话
        redis: Redis 客户端
        background_tasks: 后台任务
        
    Returns:
        User: 用户对象，如果未提供 API key 则返回 None
        
    Raises:
        HTTPException: API key 无效或用户不存在时抛出错误
    """
    if not x_goog_api_key:
        return None
    
    try:
        # 使用缓存认证
        return await get_user_from_api_key_with_cache(x_goog_api_key, db, redis, background_tasks)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"API密钥认证失败: {str(e)}"
        )


async def get_user_flexible_with_goog_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    goog_api_key_user: Optional[User] = Depends(get_user_from_goog_api_key),
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
    redis: RedisClient = Depends(get_redis),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> User:
    """
    灵活认证：支持 JWT token、Bearer API key 或 x-goog-api-key 标头
    用于 Gemini 兼容的 API 端点
    
    优先级：
    1. x-goog-api-key 标头
    2. Authorization Bearer token (JWT 或 API key)
    
    优化：
    1. API key 认证使用 Redis 缓存
    2. update_last_used 改为后台任务
    
    Args:
        credentials: HTTP Authorization 凭证
        goog_api_key_user: 通过 x-goog-api-key 标头获取的用户
        db: 数据库会话
        auth_service: 认证服务
        redis: Redis 客户端
        background_tasks: 后台任务
        
    Returns:
        User: 用户对象
        
    Raises:
        HTTPException: 认证失败
    """
    # 优先使用 x-goog-api-key 标头
    if goog_api_key_user:
        return goog_api_key_user
    
    # 如果没有 x-goog-api-key，检查 Authorization 标头
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要提供认证凭证（x-goog-api-key 标头或 Authorization Bearer token）",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    try:
        # 判断是 API key 还是 JWT token
        if token.startswith('sk-'):
            # API key 认证（使用缓存）
            return await get_user_from_api_key_with_cache(token, db, redis, background_tasks)
        else:
            # JWT token 认证
            user = await auth_service.get_current_user(token)
            return user
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"认证失败: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )