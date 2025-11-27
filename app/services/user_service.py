"""
用户服务
提供用户查询、创建、更新等功能
"""
from typing import Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.exceptions import UserNotFoundError, UserAlreadyExistsError
from app.repositories.user_repository import UserRepository
from app.repositories.oauth_token_repository import OAuthTokenRepository
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate, OAuthUserCreate
from app.schemas.token import OAuthTokenData


class UserService:
    """用户服务类"""
    
    def __init__(self, db: AsyncSession):
        """
        初始化用户服务
        
        Args:
            db: 数据库会话
        """
        self.db = db
        self.user_repo = UserRepository(db)
        self.token_repo = OAuthTokenRepository(db)
    
    # ==================== 用户查询功能 ====================
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        根据 ID 获取用户
        
        Args:
            user_id: 用户 ID
            
        Returns:
            User 对象,不存在返回 None
        """
        return await self.user_repo.get_by_id(user_id)
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """
        根据用户名获取用户
        
        Args:
            username: 用户名
            
        Returns:
            User 对象,不存在返回 None
        """
        return await self.user_repo.get_by_username(username)
    
    async def get_user_by_oauth_id(self, oauth_id: str) -> Optional[User]:
        """
        根据 OAuth ID 获取用户
        
        Args:
            oauth_id: OAuth ID
            
        Returns:
            User 对象,不存在返回 None
        """
        return await self.user_repo.get_by_oauth_id(oauth_id)
    
    # ==================== 用户创建和更新 ====================
    
    async def create_user(self, user_data: UserCreate) -> User:
        """
        创建新用户
        
        Args:
            user_data: 用户创建数据
            
        Returns:
            创建的 User 对象
            
        Raises:
            UserAlreadyExistsError: 用户名或 OAuth ID 已存在
        """
        # 处理密码
        password_hash = None
        if user_data.password:
            password_hash = hash_password(user_data.password)
        
        # 创建用户
        user = await self.user_repo.create(
            username=user_data.username,
            password_hash=password_hash,
            oauth_id=user_data.oauth_id,
            avatar_url=user_data.avatar_url,
            trust_level=user_data.trust_level
        )
        
        return user
    
    async def create_user_from_oauth(
        self,
        oauth_data: OAuthUserCreate
    ) -> User:
        """
        从 OAuth 数据创建用户
        
        Args:
            oauth_data: OAuth 用户数据
            
        Returns:
            创建的 User 对象
            
        Raises:
            UserAlreadyExistsError: 用户名或 OAuth ID 已存在
        """
        # 检查 OAuth ID 是否已存在
        existing_user = await self.get_user_by_oauth_id(oauth_data.oauth_id)
        if existing_user:
            # 用户已存在,更新信息
            return await self.update_user_info(
                user_id=existing_user.id,
                avatar_url=oauth_data.avatar_url,
                trust_level=oauth_data.trust_level
            )
        
        # 创建新用户
        user = await self.user_repo.create(
            username=oauth_data.username,
            password_hash=None,  # OAuth 用户不需要密码
            oauth_id=oauth_data.oauth_id,
            avatar_url=oauth_data.avatar_url,
            trust_level=oauth_data.trust_level
        )
        
        return user
    
    async def update_user_info(
        self,
        user_id: int,
        **kwargs
    ) -> User:
        """
        更新用户基本信息
        
        Args:
            user_id: 用户 ID
            **kwargs: 要更新的字段及其值
            
        Returns:
            更新后的 User 对象
            
        Raises:
            UserNotFoundError: 用户不存在
        """
        return await self.user_repo.update(user_id, **kwargs)
    
    async def update_user(
        self,
        user_id: int,
        user_data: UserUpdate
    ) -> User:
        """
        更新用户信息
        
        Args:
            user_id: 用户 ID
            user_data: 用户更新数据
            
        Returns:
            更新后的 User 对象
            
        Raises:
            UserNotFoundError: 用户不存在
        """
        # 只更新提供的字段
        update_data = user_data.model_dump(exclude_unset=True)
        return await self.user_repo.update(user_id, **update_data)
    
    async def update_last_login(self, user_id: int) -> User:
        """
        更新用户最后登录时间
        
        Args:
            user_id: 用户 ID
            
        Returns:
            更新后的 User 对象
            
        Raises:
            UserNotFoundError: 用户不存在
        """
        return await self.user_repo.update_last_login(user_id)
    
    # ==================== Beta 计划功能 ====================
    
    async def join_beta(self, user_id: int) -> User:
        """
        加入 Beta 计划
        
        Args:
            user_id: 用户 ID
            
        Returns:
            更新后的 User 对象
            
        Raises:
            UserNotFoundError: 用户不存在
        """
        return await self.user_repo.update(user_id, beta=1)
    
    async def leave_beta(self, user_id: int) -> User:
        """
        退出 Beta 计划
        
        Args:
            user_id: 用户 ID
            
        Returns:
            更新后的 User 对象
            
        Raises:
            UserNotFoundError: 用户不存在
        """
        return await self.user_repo.update(user_id, beta=0)
    
    async def get_beta_status(self, user_id: int) -> int:
        """
        获取用户的 Beta 计划状态
        
        Args:
            user_id: 用户 ID
            
        Returns:
            Beta 状态值
            
        Raises:
            UserNotFoundError: 用户不存在
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(
                message=f"用户 ID {user_id} 不存在",
                details={"user_id": user_id}
            )
        return user.beta
    
    # ==================== OAuth 令牌存储 ====================
    
    async def save_oauth_token(
        self,
        user_id: int,
        token_data: OAuthTokenData,
        expires_at: datetime
    ) -> bool:
        """
        保存或更新用户的 OAuth 令牌
        
        Args:
            user_id: 用户 ID
            token_data: OAuth 令牌数据
            expires_at: 过期时间
            
        Returns:
            保存成功返回 True
        """
        try:
            await self.token_repo.update(
                user_id=user_id,
                access_token=token_data.access_token,
                refresh_token=token_data.refresh_token,
                token_type=token_data.token_type,
                expires_at=expires_at
            )
            return True
        except Exception:
            return False
    
    async def get_oauth_token(self, user_id: int):
        """
        获取用户的 OAuth 令牌
        
        Args:
            user_id: 用户 ID
            
        Returns:
            OAuthToken 对象,不存在返回 None
        """
        return await self.token_repo.get_by_user_id(user_id)
    
    # ==================== 用户验证 ====================
    
    async def is_username_available(self, username: str) -> bool:
        """
        检查用户名是否可用
        
        Args:
            username: 用户名
            
        Returns:
            可用返回 True
        """
        user = await self.get_user_by_username(username)
        return user is None
    
    async def is_oauth_id_available(self, oauth_id: str) -> bool:
        """
        检查 OAuth ID 是否可用
        
        Args:
            oauth_id: OAuth ID
            
        Returns:
            可用返回 True
        """
        user = await self.get_user_by_oauth_id(oauth_id)
        return user is None