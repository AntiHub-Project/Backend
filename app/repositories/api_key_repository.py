"""
API密钥Repository
处理API密钥的数据库操作
"""
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.models.api_key import APIKey


class APIKeyRepository:
    """API密钥Repository类"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, user_id: int, name: Optional[str] = None, config_type: str = "antigravity") -> APIKey:
        """
        创建新的API密钥
        
        Args:
            user_id: 用户ID
            name: 密钥名称
            config_type: 配置类型（antigravity 或 kiro）
            
        Returns:
            创建的API密钥对象
        """
        api_key = APIKey(
            user_id=user_id,
            key=APIKey.generate_key(),
            name=name,
            config_type=config_type
        )
        self.db.add(api_key)
        await self.db.flush()
        await self.db.refresh(api_key)
        return api_key
    
    async def get_by_key(self, key: str) -> Optional[APIKey]:
        """
        通过密钥获取API密钥对象
        
        Args:
            key: API密钥
            
        Returns:
            API密钥对象，不存在返回None
        """
        result = await self.db.execute(
            select(APIKey).where(APIKey.key == key)
        )
        return result.scalar_one_or_none()
    
    async def get_by_user_id(self, user_id: int) -> List[APIKey]:
        """
        获取用户的所有API密钥
        
        Args:
            user_id: 用户ID
            
        Returns:
            API密钥列表
        """
        result = await self.db.execute(
            select(APIKey)
            .where(APIKey.user_id == user_id)
            .order_by(APIKey.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def get_by_id(self, key_id: int) -> Optional[APIKey]:
        """
        通过ID获取API密钥
        
        Args:
            key_id: 密钥ID
            
        Returns:
            API密钥对象，不存在返回None
        """
        result = await self.db.execute(
            select(APIKey).where(APIKey.id == key_id)
        )
        return result.scalar_one_or_none()
    
    async def update_last_used(self, key: str) -> None:
        """
        更新密钥最后使用时间
        
        Args:
            key: API密钥
        """
        api_key = await self.get_by_key(key)
        if api_key:
            api_key.last_used_at = datetime.utcnow()
            await self.db.flush()
    
    async def delete(self, key_id: int, user_id: int) -> bool:
        """
        删除API密钥
        
        Args:
            key_id: 密钥ID
            user_id: 用户ID（用于验证权限）
            
        Returns:
            删除成功返回True
        """
        api_key = await self.get_by_id(key_id)
        if api_key and api_key.user_id == user_id:
            await self.db.delete(api_key)
            await self.db.flush()
            return True
        return False
    
    async def update_status(self, key_id: int, user_id: int, is_active: bool) -> Optional[APIKey]:
        """
        更新密钥状态
        
        Args:
            key_id: 密钥ID
            user_id: 用户ID（用于验证权限）
            is_active: 是否激活
            
        Returns:
            更新后的API密钥对象
        """
        api_key = await self.get_by_id(key_id)
        if api_key and api_key.user_id == user_id:
            api_key.is_active = is_active
            await self.db.flush()
            await self.db.refresh(api_key)
            return api_key
        return None