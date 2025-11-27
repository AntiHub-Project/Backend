"""
用户API密钥模型
用于存储我们系统生成的API密钥，用户使用这些密钥调用我们的API
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import secrets

from app.db.base import Base


class APIKey(Base):
    """用户API密钥表"""
    
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(128), unique=True, nullable=False, index=True)  # 我们生成的API key
    name = Column(String(100), nullable=True)  # 密钥名称，方便用户识别
    config_type = Column(String(50), default="antigravity", nullable=False)  # 配置类型：antigravity 或 kiro
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # 过期时间，可选
    
    # 关系
    user = relationship("User", back_populates="api_keys")
    
    @staticmethod
    def generate_key() -> str:
        """生成一个新的API密钥"""
        return f"sk-{secrets.token_urlsafe(48)}"
    
    def __repr__(self):
        return f"<APIKey(id={self.id}, user_id={self.user_id}, name={self.name})>"