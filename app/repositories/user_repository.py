"""
用户数据仓储
提供用户数据的增删改查操作
"""
from typing import Optional
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.core.exceptions import UserNotFoundError, UserAlreadyExistsError


class UserRepository:
    """用户数据仓储类"""
    
    def __init__(self, db: AsyncSession):
        """
        初始化仓储
        
        Args:
            db: 数据库会话
        """
        self.db = db
    
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """
        根据 ID 获取用户
        
        Args:
            user_id: 用户 ID
            
        Returns:
            User 对象,不存在返回 None
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_username(self, username: str) -> Optional[User]:
        """
        根据用户名获取用户
        
        Args:
            username: 用户名
            
        Returns:
            User 对象,不存在返回 None
        """
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()
    
    async def get_by_oauth_id(self, oauth_id: str) -> Optional[User]:
        """
        根据 OAuth ID 获取用户
        
        Args:
            oauth_id: OAuth 提供商的用户 ID
            
        Returns:
            User 对象,不存在返回 None
        """
        result = await self.db.execute(
            select(User).where(User.oauth_id == oauth_id)
        )
        return result.scalar_one_or_none()
    
    async def create(
        self,
        username: str,
        password_hash: Optional[str] = None,
        oauth_id: Optional[str] = None,
        avatar_url: Optional[str] = None,
        trust_level: int = 0,
        is_active: bool = True,
        is_silenced: bool = False,
        beta: int = 0
    ) -> User:
        """
        创建新用户
        
        Args:
            username: 用户名
            password_hash: 密码哈希(传统用户)
            oauth_id: OAuth ID(OAuth 用户)
            avatar_url: 头像 URL
            trust_level: 信任等级
            is_active: 是否激活
            is_silenced: 是否禁言
            beta: 是否加入beta计划
            
        Returns:
            创建的 User 对象
            
        Raises:
            UserAlreadyExistsError: 用户名或 OAuth ID 已存在
        """
        # 检查用户名是否已存在
        existing_user = await self.get_by_username(username)
        if existing_user:
            raise UserAlreadyExistsError(
                message=f"用户名 '{username}' 已存在",
                details={"username": username}
            )
        
        # 检查 OAuth ID 是否已存在
        if oauth_id:
            existing_oauth_user = await self.get_by_oauth_id(oauth_id)
            if existing_oauth_user:
                raise UserAlreadyExistsError(
                    message=f"OAuth ID '{oauth_id}' 已存在",
                    details={"oauth_id": oauth_id}
                )
        
        # 创建新用户
        user = User(
            username=username,
            password_hash=password_hash,
            oauth_id=oauth_id,
            avatar_url=avatar_url,
            trust_level=trust_level,
            is_active=is_active,
            is_silenced=is_silenced,
            beta=beta
        )
        
        self.db.add(user)
        await self.db.flush()  # 刷新到数据库但不提交
        await self.db.refresh(user)
        
        return user
    
    async def update(
        self,
        user_id: int,
        **kwargs
    ) -> User:
        """
        更新用户信息
        
        Args:
            user_id: 用户 ID
            **kwargs: 要更新的字段及其值
            
        Returns:
            更新后的 User 对象
            
        Raises:
            UserNotFoundError: 用户不存在
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(
                message=f"用户 ID {user_id} 不存在",
                details={"user_id": user_id}
            )
        
        # 更新允许的字段
        allowed_fields = {
            'username', 'password_hash', 'oauth_id', 'avatar_url',
            'trust_level', 'is_active', 'is_silenced', 'last_login_at', 'beta'
        }
        
        for field, value in kwargs.items():
            if field in allowed_fields and hasattr(user, field):
                setattr(user, field, value)
        
        # 不在这里提交，由会话管理器统一处理
        await self.db.flush()  # 将更改刷新到数据库但不提交
        await self.db.refresh(user)
        
        return user
    
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
        return await self.update(
            user_id=user_id,
            last_login_at=datetime.utcnow()
        )
    
    async def delete(self, user_id: int) -> bool:
        """
        删除用户
        
        Args:
            user_id: 用户 ID
            
        Returns:
            删除成功返回 True
            
        Raises:
            UserNotFoundError: 用户不存在
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(
                message=f"用户 ID {user_id} 不存在",
                details={"user_id": user_id}
            )
        
        await self.db.delete(user)
        # 删除操作也由会话管理器统一提交
        await self.db.flush()
        
        return True
    
    async def is_username_taken(self, username: str) -> bool:
        """
        检查用户名是否已被使用
        
        Args:
            username: 用户名
            
        Returns:
            已被使用返回 True,否则返回 False
        """
        user = await self.get_by_username(username)
        return user is not None
    
    async def is_oauth_id_taken(self, oauth_id: str) -> bool:
        """
        检查 OAuth ID 是否已被使用
        
        Args:
            oauth_id: OAuth ID
            
        Returns:
            已被使用返回 True,否则返回 False
        """
        user = await self.get_by_oauth_id(oauth_id)
        return user is not None