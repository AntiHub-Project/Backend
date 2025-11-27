"""
用户相关的 Pydantic Schema
定义用户数据的请求和响应模型
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ==================== 用户基础 Schema ====================

class UserBase(BaseModel):
    """用户基础信息"""
    
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="用户名"
    )
    avatar_url: Optional[str] = Field(
        None,
        max_length=512,
        description="用户头像 URL"
    )
    trust_level: int = Field(
        default=0,
        ge=0,
        description="用户信任等级"
    )


class UserCreate(UserBase):
    """创建用户请求"""
    
    password: Optional[str] = Field(
        None,
        min_length=6,
        max_length=100,
        description="密码(传统用户需要)"
    )
    oauth_id: Optional[str] = Field(
        None,
        max_length=255,
        description="OAuth ID(OAuth 用户需要)"
    )
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "username": "johndoe",
                    "password": "secretpassword123",
                    "avatar_url": "https://example.com/avatar.jpg",
                    "trust_level": 0
                }
            ]
        }
    }


class UserUpdate(BaseModel):
    """更新用户请求"""
    
    username: Optional[str] = Field(
        None,
        min_length=3,
        max_length=50,
        description="用户名"
    )
    avatar_url: Optional[str] = Field(
        None,
        max_length=512,
        description="用户头像 URL"
    )
    trust_level: Optional[int] = Field(
        None,
        ge=0,
        description="用户信任等级"
    )
    is_active: Optional[bool] = Field(
        None,
        description="账号是否激活"
    )
    is_silenced: Optional[bool] = Field(
        None,
        description="是否被禁言"
    )
    beta: Optional[int] = Field(
        None,
        ge=0,
        description="是否加入beta计划"
    )
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "avatar_url": "https://example.com/new-avatar.jpg",
                    "trust_level": 1
                }
            ]
        }
    }


# ==================== 用户响应 Schema ====================

class UserResponse(BaseModel):
    """用户响应(公开信息)"""
    
    id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    avatar_url: Optional[str] = Field(None, description="用户头像 URL")
    trust_level: int = Field(..., description="用户信任等级")
    is_active: bool = Field(..., description="账号是否激活")
    is_silenced: bool = Field(..., description="是否被禁言")
    beta: int = Field(default=0, description="是否加入beta计划")
    created_at: datetime = Field(..., description="创建时间")
    last_login_at: Optional[datetime] = Field(None, description="最后登录时间")
    
    model_config = ConfigDict(from_attributes=True)


class UserInDB(UserResponse):
    """用户数据库模型(包含敏感信息)"""
    
    password_hash: Optional[str] = Field(None, description="密码哈希值")
    oauth_id: Optional[str] = Field(None, description="OAuth ID")
    updated_at: datetime = Field(..., description="更新时间")
    
    model_config = ConfigDict(from_attributes=True)


class UserProfile(UserResponse):
    """用户详细资料(包含更多信息)"""
    
    oauth_id: Optional[str] = Field(None, description="OAuth ID")
    updated_at: datetime = Field(..., description="更新时间")
    
    model_config = ConfigDict(from_attributes=True)


# ==================== OAuth 用户创建 Schema ====================

class OAuthUserCreate(BaseModel):
    """从 OAuth 数据创建用户"""
    
    oauth_id: str = Field(..., description="OAuth 提供商的用户 ID")
    username: str = Field(..., description="用户名")
    avatar_url: Optional[str] = Field(None, description="用户头像 URL")
    trust_level: int = Field(default=0, description="用户信任等级")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "oauth_id": "oauth_123456",
                    "username": "johndoe",
                    "avatar_url": "https://example.com/avatar.jpg",
                    "trust_level": 0
                }
            ]
        }
    }


# ==================== Beta 计划 Schema ====================

class JoinBetaResponse(BaseModel):
    """加入beta计划响应"""
    
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")
    beta: int = Field(..., description="当前beta状态")
    
    model_config = ConfigDict(from_attributes=True)