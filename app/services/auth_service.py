"""
认证服务
提供用户认证、JWT 令牌管理、会话管理等功能
"""
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError as JWTInvalidTokenError

from app.core.security import (
    verify_password,
    create_access_token,
    verify_access_token,
    create_refresh_token,
    verify_refresh_token,
    generate_token_pair,
    extract_token_jti,
    get_token_remaining_seconds,
)
from app.core.config import get_settings
from app.core.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
    TokenBlacklistedError,
    UserNotFoundError,
    AccountDisabledError,
    AccountSilencedError,
)
from app.repositories.user_repository import UserRepository
from app.cache.redis_client import RedisClient
from app.models.user import User
from app.schemas.token import TokenPayload

logger = logging.getLogger(__name__)

# JWT 用户缓存 TTL（秒）- 较短，因为 JWT 本身有过期时间
JWT_USER_CACHE_TTL = 30


class AuthService:
    """认证服务类"""
    
    def __init__(self, db: AsyncSession, redis: RedisClient):
        """
        初始化认证服务
        
        Args:
            db: 数据库会话
            redis: Redis 客户端
        """
        self.db = db
        self.redis = redis
        self.user_repo = UserRepository(db)
        self._settings = get_settings()
    
    async def authenticate_user(
        self,
        username: str,
        password: str
    ) -> User:
        """
        验证用户名和密码
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            验证成功的 User 对象
            
        Raises:
            InvalidCredentialsError: 用户名或密码错误
            AccountDisabledError: 账号已被禁用
        """
        # 获取用户
        user = await self.user_repo.get_by_username(username)
        if not user:
            raise InvalidCredentialsError(
                message="用户名或密码错误",
                details={"username": username}
            )
        
        # 检查密码
        if not user.password_hash:
            raise InvalidCredentialsError(
                message="该账号未设置密码,请使用 OAuth 登录"
            )
        
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError(
                message="用户名或密码错误"
            )
        
        # 检查账号状态
        if not user.is_active:
            raise AccountDisabledError(
                message="账号已被禁用",
                details={"user_id": user.id}
            )
        
        return user
    
    async def create_user_token(
        self,
        user: User,
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        为用户创建 JWT 访问令牌
        
        Args:
            user: 用户对象
            additional_claims: 额外的声明数据
            
        Returns:
            JWT 令牌字符串
        """
        token = create_access_token(
            user_id=user.id,
            username=user.username,
            additional_claims=additional_claims
        )
        return token
    
    async def create_token_pair(
        self,
        user: User,
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str]:
        """
        为用户创建 Access Token 和 Refresh Token 对
        
        Args:
            user: 用户对象
            additional_claims: 额外的声明数据
            
        Returns:
            (access_token, refresh_token) 元组
        """
        access_token, refresh_token = generate_token_pair(
            user_id=user.id,
            username=user.username,
            additional_claims=additional_claims
        )
        
        # 存储 refresh token 到 Redis
        refresh_jti = extract_token_jti(refresh_token)
        if refresh_jti:
            token_data = {
                "user_id": user.id,
                "username": user.username,
                "created_at": datetime.utcnow().isoformat()
            }
            await self.redis.store_refresh_token(
                user_id=user.id,
                token_jti=refresh_jti,
                token_data=token_data,
                ttl=self._settings.refresh_token_expire_seconds
            )
        
        return access_token, refresh_token
    
    async def verify_token(self, token: str) -> TokenPayload:
        """
        验证 JWT 令牌
        
        Args:
            token: JWT 令牌字符串
            
        Returns:
            令牌 payload
            
        Raises:
            InvalidTokenError: 令牌无效
            TokenExpiredError: 令牌已过期
            TokenBlacklistedError: 令牌已被加入黑名单
        """
        try:
            # 验证令牌
            payload = verify_access_token(token)
            if not payload:
                raise InvalidTokenError(message="令牌无效")
            
            # 检查令牌是否在黑名单中
            jti = payload.get("jti")
            if jti and await self.is_token_blacklisted(jti):
                raise TokenBlacklistedError(
                    message="令牌已失效",
                    details={"jti": jti}
                )
            
            return TokenPayload(**payload)
            
        except ExpiredSignatureError:
            raise TokenExpiredError(message="令牌已过期")
        except JWTInvalidTokenError:
            raise InvalidTokenError(message="令牌无效")
        except Exception as e:
            if "expired" in str(e).lower():
                raise TokenExpiredError(message="令牌已过期")
            raise InvalidTokenError(
                message="令牌无效",
                details={"error": str(e)}
            )
    
    async def refresh_tokens(
        self,
        refresh_token: str
    ) -> Tuple[str, str, User]:
        """
        使用 Refresh Token 刷新令牌对
        
        Args:
            refresh_token: Refresh Token 字符串
            
        Returns:
            (new_access_token, new_refresh_token, user) 元组
            
        Raises:
            InvalidTokenError: Refresh Token 无效
            TokenExpiredError: Refresh Token 已过期
            TokenBlacklistedError: Refresh Token 已被撤销
            UserNotFoundError: 用户不存在
            AccountDisabledError: 账号已被禁用
        """
        try:
            # 验证 refresh token
            payload = verify_refresh_token(refresh_token)
            if not payload:
                raise InvalidTokenError(message="Refresh Token 无效")
            
            # 检查 refresh token 是否已被撤销
            jti = payload.get("jti")
            if jti and not await self.redis.is_refresh_token_valid(jti):
                raise TokenBlacklistedError(
                    message="Refresh Token 已被撤销",
                    details={"jti": jti}
                )
            
            # 获取用户
            user_id = int(payload.get("sub"))
            user = await self.user_repo.get_by_id(user_id)
            
            if not user:
                raise UserNotFoundError(
                    message="用户不存在",
                    details={"user_id": user_id}
                )
            
            # 检查账号状态
            if not user.is_active:
                raise AccountDisabledError(
                    message="账号已被禁用",
                    details={"user_id": user.id}
                )
            
            # 生成新的令牌对
            new_access_token, new_refresh_token = await self.create_token_pair(user)
            
            # 轮换 refresh token（撤销旧的）
            new_refresh_jti = extract_token_jti(new_refresh_token)
            if jti and new_refresh_jti:
                await self.redis.revoke_refresh_token(jti)
            
            return new_access_token, new_refresh_token, user
            
        except ExpiredSignatureError:
            raise TokenExpiredError(message="Refresh Token 已过期")
        except JWTInvalidTokenError:
            raise InvalidTokenError(message="Refresh Token 无效")
        except (TokenBlacklistedError, UserNotFoundError, AccountDisabledError):
            raise
        except Exception as e:
            if "expired" in str(e).lower():
                raise TokenExpiredError(message="Refresh Token 已过期")
            raise InvalidTokenError(
                message="Refresh Token 无效",
                details={"error": str(e)}
            )
    
    async def get_current_user(self, token: str) -> User:
        """
        根据令牌获取当前用户
        
        优化：添加短期 Redis 缓存减少数据库查询
        
        Args:
            token: JWT 令牌字符串
            
        Returns:
            User 对象
            
        Raises:
            InvalidTokenError: 令牌无效
            UserNotFoundError: 用户不存在
            AccountDisabledError: 账号已被禁用
        """
        try:
            # 验证令牌
            payload = await self.verify_token(token)
            user_id = int(payload.sub)
            
            # 尝试从缓存获取用户信息
            cache_key = f"jwt_user:{user_id}"
            try:
                cached_data = await self.redis.get_json(cache_key)
                if cached_data:
                    logger.debug(f"从缓存获取 JWT 用户信息: user_id={user_id}")
                    user = User(
                        id=cached_data["id"],
                        username=cached_data["username"],
                        is_active=cached_data["is_active"],
                        beta=cached_data.get("beta", 0)
                    )
                    return user
            except Exception as e:
                logger.warning(f"Redis 缓存读取失败 (user_id={user_id}): {type(e).__name__}: {str(e)}")
            
            # 缓存未命中，从数据库获取
            try:
                user = await self.user_repo.get_by_id(user_id)
            except Exception as e:
                logger.error(f"数据库查询用户失败 (user_id={user_id}): {type(e).__name__}: {str(e)}", exc_info=True)
                raise
            
            if not user:
                logger.warning(f"用户不存在: user_id={user_id}")
                raise UserNotFoundError(
                    message="用户不存在",
                    details={"user_id": user_id}
                )
            
            # 检查账号状态
            if not user.is_active:
                logger.warning(f"账号已被禁用: user_id={user.id}")
                raise AccountDisabledError(
                    message="账号已被禁用",
                    details={"user_id": user.id}
                )
            
            # 存入缓存（短期缓存，30秒）
            try:
                user_data = {
                    "id": user.id,
                    "username": user.username,
                    "is_active": user.is_active,
                    "beta": user.beta
                }
                await self.redis.set_json(cache_key, user_data, expire=JWT_USER_CACHE_TTL)
                logger.debug(f"JWT 用户信息已缓存: user_id={user_id}, TTL={JWT_USER_CACHE_TTL}s")
            except Exception as e:
                logger.warning(f"Redis 缓存写入失败 (user_id={user_id}): {type(e).__name__}: {str(e)}")
            
            return user
            
        except (InvalidTokenError, TokenExpiredError, TokenBlacklistedError, UserNotFoundError, AccountDisabledError):
            # 这些是预期的业务异常，直接抛出
            raise
        except Exception as e:
            # 未预期的异常，记录详细日志
            logger.error(f"获取当前用户时发生未预期错误: {type(e).__name__}: {str(e)}", exc_info=True)
            raise
    
    # ==================== 会话管理 ====================
    
    async def create_session(
        self,
        user_id: int,
        token: str,
        ttl: int = 86400  # 24小时
    ) -> bool:
        """
        创建用户会话
        
        Args:
            user_id: 用户 ID
            token: JWT 令牌
            ttl: 会话有效期(秒)
            
        Returns:
            创建成功返回 True
        """
        session_data = {
            "user_id": user_id,
            "token": token,
            "created_at": datetime.utcnow().isoformat()
        }
        return await self.redis.create_session(user_id, session_data, ttl)
    
    async def get_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        获取用户会话
        
        Args:
            user_id: 用户 ID
            
        Returns:
            会话数据,不存在返回 None
        """
        return await self.redis.get_session(user_id)
    
    async def delete_session(self, user_id: int) -> bool:
        """
        删除用户会话
        
        Args:
            user_id: 用户 ID
            
        Returns:
            删除成功返回 True
        """
        return await self.redis.delete_session(user_id)
    
    # ==================== 令牌黑名单管理 ====================
    
    async def blacklist_token(self, token: str) -> bool:
        """
        将令牌加入黑名单
        
        Args:
            token: JWT 令牌字符串
            
        Returns:
            添加成功返回 True
        """
        # 提取 JTI
        jti = extract_token_jti(token)
        if not jti:
            return False
        
        # 获取令牌剩余有效时间
        remaining_seconds = get_token_remaining_seconds(token)
        if not remaining_seconds or remaining_seconds <= 0:
            # 令牌已过期,无需加入黑名单
            return True
        
        # 加入黑名单
        return await self.redis.blacklist_token(jti, remaining_seconds)
    
    async def is_token_blacklisted(self, jti: str) -> bool:
        """
        检查令牌是否在黑名单中
        
        Args:
            jti: JWT ID
            
        Returns:
            在黑名单中返回 True
        """
        return await self.redis.is_token_blacklisted(jti)
    
    # ==================== 登录登出流程 ====================
    
    async def login(
        self,
        username: str,
        password: str
    ) -> Tuple[str, str, User]:
        """
        用户登录
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            (access_token, refresh_token, User 对象)
        """
        # 验证用户
        user = await self.authenticate_user(username, password)
        
        # 更新最后登录时间
        await self.user_repo.update_last_login(user.id)
        
        # 创建令牌对
        access_token, refresh_token = await self.create_token_pair(user)
        
        # 创建会话
        await self.create_session(user.id, access_token)
        
        return access_token, refresh_token, user
    
    async def logout(
        self,
        user_id: int,
        access_token: str,
        refresh_token: Optional[str] = None
    ) -> bool:
        """
        用户登出
        
        Args:
            user_id: 用户 ID
            access_token: JWT 访问令牌
            refresh_token: Refresh Token（可选）
            
        Returns:
            登出成功返回 True
        """
        # 删除会话
        await self.delete_session(user_id)
        
        # 将 access token 加入黑名单
        await self.blacklist_token(access_token)
        
        # 如果提供了 refresh token，撤销它
        if refresh_token:
            refresh_jti = extract_token_jti(refresh_token)
            if refresh_jti:
                await self.redis.revoke_refresh_token(refresh_jti)
        
        return True
    
    async def logout_all_devices(self, user_id: int) -> bool:
        """
        登出所有设备（撤销用户的所有 refresh token）
        
        Args:
            user_id: 用户 ID
            
        Returns:
            登出成功返回 True
        """
        # 删除会话
        await self.delete_session(user_id)
        
        # 撤销所有 refresh token
        await self.redis.revoke_all_user_refresh_tokens(user_id)
        
        return True