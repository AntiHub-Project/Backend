"""
Kiro账号相关的数据模式
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ==================== Kiro账号相关 ====================

class KiroOAuthAuthorizeRequest(BaseModel):
    """获取Kiro OAuth授权URL请求"""
    provider: str = Field(..., description="OAuth提供商: Google 或 Github")
    is_shared: int = Field(0, description="0=专属cookie，1=共享cookie")


class KiroAccountCreate(BaseModel):
    """创建Kiro账号请求"""
    account_name: str = Field(..., description="账号名称")
    auth_method: str = Field(..., description="认证方法: Social 或 IdC")
    refresh_token: str = Field(..., description="AWS刷新令牌")
    client_id: Optional[str] = Field(None, description="IdC客户端ID（IdC认证时必填）")
    client_secret: Optional[str] = Field(None, description="IdC客户端密钥（IdC认证时必填）")


class KiroAccountResponse(BaseModel):
    """Kiro账号响应"""
    account_id: int = Field(..., alias="id")
    user_id: int
    account_name: str
    auth_method: str
    status: int
    expires_at: Optional[int] = None
    email: Optional[str] = None
    subscription: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True, "populate_by_name": True}


class KiroAccountUpdate(BaseModel):
    """更新Kiro账号"""
    account_name: Optional[str] = Field(None, description="账号名称")
    status: Optional[int] = Field(None, description="账号状态：0=禁用，1=启用")


class KiroAccountBalance(BaseModel):
    """Kiro账号余额信息"""
    account_id: int
    account_name: str
    email: Optional[str] = None
    subscription: Optional[str] = None
    balance: Dict[str, Any] = Field(..., description="余额详情")
    raw_data: Dict[str, Any] = Field(..., description="原始数据")


# ==================== Kiro消费日志相关 ====================

class KiroConsumptionLogResponse(BaseModel):
    """Kiro消费日志响应"""
    log_id: int = Field(..., alias="id")
    account_id: int
    model_id: str
    credit_used: float
    is_shared: int
    consumed_at: datetime
    account_name: Optional[str] = None
    
    model_config = {"from_attributes": True, "populate_by_name": True}


class KiroConsumptionStats(BaseModel):
    """Kiro消费统计"""
    model_id: str
    request_count: str
    total_credit: str
    avg_credit: str
    min_credit: str
    max_credit: str


class KiroConsumptionQuery(BaseModel):
    """Kiro消费查询参数"""
    limit: int = Field(100, description="每页数量")
    offset: int = Field(0, description="偏移量")
    start_date: Optional[str] = Field(None, description="开始日期（ISO格式）")
    end_date: Optional[str] = Field(None, description="结束日期（ISO格式）")


class KiroConsumptionResponse(BaseModel):
    """Kiro消费记录响应"""
    account_id: int
    account_name: str
    logs: List[KiroConsumptionLogResponse]
    stats: List[KiroConsumptionStats]
    pagination: Dict[str, int]


class KiroUserConsumptionStats(BaseModel):
    """用户总消费统计"""
    total_requests: str
    total_credit: str
    avg_credit: str
    shared_credit: str
    private_credit: str


# ==================== 通用响应 ====================

class KiroAPIResponse(BaseModel):
    """通用Kiro API响应"""
    success: bool
    message: Optional[str] = None
    data: Optional[Any] = None