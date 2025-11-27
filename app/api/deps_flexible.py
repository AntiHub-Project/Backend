"""
灵活的认证依赖
支持JWT token或API key两种认证方式
"""
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.repositories.api_key_repository import APIKeyRepository
from app.repositories.user_repository import UserRepository
from app.api.deps import get_auth_service


security = HTTPBearer()


async def get_user_flexible(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
) -> User:
    """
    灵活认证：支持JWT token或API key
    
    - 如果token以'sk-'开头，视为API key
    - 否则视为JWT token
    
    Args:
        credentials: HTTP Authorization凭证
        db: 数据库会话
        auth_service: 认证服务
        
    Returns:
        User: 用户对象
        
    Raises:
        HTTPException: 认证失败
    """
    token = credentials.credentials
    
    try:
        # 判断是API key还是JWT token
        if token.startswith('sk-'):
            # API key认证
            repo = APIKeyRepository(db)
            key_record = await repo.get_by_key(token)
            
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
            await repo.update_last_used(token)
            await db.commit()
            
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
            
            return user
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