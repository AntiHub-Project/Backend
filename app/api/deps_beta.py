"""
Beta功能权限依赖
只有beta用户才能使用的功能
"""
from fastapi import Depends, HTTPException, status
from app.models.user import User
from app.api.deps import get_current_user, get_user_from_api_key

async def require_beta_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    要求用户必须是beta用户
    用于需要JWT token认证的beta功能
    
    Args:
        current_user: 当前用户
        
    Returns:
        User: beta用户对象
        
    Raises:
        HTTPException: 用户不是beta用户时抛出403错误
    """
    if current_user.beta !=1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此功能仅对beta计划用户开放，请联系管理员加入beta计划"
        )
    return current_user

async def require_beta_user_api_key(
    current_user: User = Depends(get_user_from_api_key)
) -> User:
    """
    要求用户必须是beta用户（API key认证）
    用于需要API key认证的beta功能
    
    Args:
        current_user: 当前用户
        
    Returns:
        User: beta用户对象
        
    Raises:
        HTTPException: 用户不是beta用户时抛出403错误
    """
    if current_user.beta != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此功能仅对beta计划用户开放，请联系管理员加入beta计划"
        )
    return current_user

async def require_beta_user_flexible(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    要求用户必须是beta用户（灵活认证）
    支持JWT token或API key认证
    
    Args:
        current_user: 当前用户
        
    Returns:
        User: beta用户对象
        
    Raises:
        HTTPException: 用户不是beta用户时抛出403错误
    """
    if current_user.beta != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此功能仅对beta计划用户开放，请联系管理员加入beta计划"
        )
    return current_user