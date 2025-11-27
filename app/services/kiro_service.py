"""
Kiro账号服务
通过插件API管理Kiro账号，不直接操作数据库
所有Kiro账号数据存储在插件API系统中
"""
from typing import Optional, Dict, Any, List
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.plugin_api_key_repository import PluginAPIKeyRepository
from app.utils.encryption import decrypt_api_key

class KiroService:
    """Kiro账号服务类- 通过插件API管理"""
    
    # 支持的Kiro模型列表
    SUPPORTED_MODELS = [
        "claude-sonnet-4-5",
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-4-20250514",
        "claude-opus-4-5-20251101",
        "claude-haiku-4-5-20251001",
    ]
    
    def __init__(self, db: AsyncSession):
        """
        初始化服务
        
        Args:
            db: 数据库会话
        """
        self.db = db
        self.settings = get_settings()
        self.plugin_api_key_repo = PluginAPIKeyRepository(db)
        self.base_url = self.settings.plugin_api_base_url
    
    async def _get_user_plugin_key(self, user_id: int) -> str:
        """
        获取用户的插件API密钥
        
        Args:
            user_id: 用户ID
            
        Returns:
            解密后的插件API密钥
        """
        key_record = await self.plugin_api_key_repo.get_by_user_id(user_id)
        if not key_record or not key_record.is_active:
            raise ValueError("用户未配置插件API密钥")
        
        return decrypt_api_key(key_record.api_key)
    
    async def _proxy_request(
        self,
        user_id: int,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        代理请求到插件API的Kiro端点
        
        Args:
            user_id: 用户ID
            method: HTTP方法
            path: API路径
            json_data: JSON数据
            params: 查询参数
            
        Returns:
            API响应
        """
        api_key = await self._get_user_plugin_key(user_id)
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=headers,timeout=300.0
            )
            response.raise_for_status()
            return response.json()
    
    async def _proxy_stream_request(
        self,
        user_id: int,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None
    ):
        """
        代理流式请求到插件API的Kiro端点
        
        Args:
            user_id: 用户ID
            method: HTTP方法
            path: API路径
            json_data: JSON数据
            
        Yields:
            流式响应数据
        """
        api_key = await self._get_user_plugin_key(user_id)
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        async with httpx.AsyncClient() as client:
            async with client.stream(
                method=method,
                url=url,
                json=json_data,
                headers=headers,
                timeout=300.0
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
    
    #==================== Kiro账号管理 ====================
    
    async def get_oauth_authorize_url(
        self,
        user_id: int,
        provider: str,
        is_shared: int = 0
    ) -> Dict[str, Any]:
        """获取Kiro OAuth授权URL（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="POST",
            path="/api/kiro/oauth/authorize",
            json_data={
                "provider": provider,
                "is_shared": is_shared
            }
        )
    
    async def get_oauth_status(self, user_id: int, state: str) -> Dict[str, Any]:
        """轮询Kiro OAuth授权状态（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="GET",
            path=f"/api/kiro/oauth/status/{state}"
        )
    
    async def create_account(self, user_id: int, account_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建Kiro账号（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="POST",
            path="/api/kiro/accounts",
            json_data=account_data
        )
    
    async def get_accounts(self, user_id: int) -> Dict[str, Any]:
        """获取Kiro账号列表（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="GET",
            path="/api/kiro/accounts"
        )
    
    async def get_account(self, user_id: int, account_id: str) -> Dict[str, Any]:
        """获取单个Kiro账号（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="GET",
            path=f"/api/kiro/accounts/{account_id}"
        )
    
    async def update_account_status(
        self,
        user_id: int,
        account_id: str,
        status: int
    ) -> Dict[str, Any]:
        """更新Kiro账号状态（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="PUT",
            path=f"/api/kiro/accounts/{account_id}/status",
            json_data={"status": status}
        )
    
    async def update_account_name(
        self,
        user_id: int,
        account_id: str,
        account_name: str
    ) -> Dict[str, Any]:
        """更新Kiro账号名称（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="PUT",
            path=f"/api/kiro/accounts/{account_id}/name",
            json_data={"account_name": account_name}
        )
    
    async def get_account_balance(self, user_id: int, account_id: str) -> Dict[str, Any]:
        """获取Kiro账号余额（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="GET",
            path=f"/api/kiro/accounts/{account_id}/balance"
        )
    
    async def get_account_consumption(
        self,
        user_id: int,
        account_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取Kiro账号消费记录（通过插件API）"""
        params = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        
        return await self._proxy_request(
            user_id=user_id,
            method="GET",
            path=f"/api/kiro/accounts/{account_id}/consumption",
            params=params
        )
    
    async def get_user_consumption_stats(
        self,
        user_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取用户Kiro总消费统计（通过插件API）"""
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        
        return await self._proxy_request(
            user_id=user_id,
            method="GET",
            path="/api/kiro/consumption/stats",
            params=params
        )
    
    async def delete_account(self, user_id: int, account_id: str) -> Dict[str, Any]:
        """删除Kiro账号（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="DELETE",
            path=f"/api/kiro/accounts/{account_id}"
        )
    
    # ==================== Kiro OpenAI兼容API ====================
    
    async def get_models(self, user_id: int) -> Dict[str, Any]:
        """获取Kiro模型列表（通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="GET",
            path="/v1/kiro/models"
        )
    
    async def chat_completions(
        self,
        user_id: int,
        request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Kiro聊天补全（非流式，通过插件API）"""
        return await self._proxy_request(
            user_id=user_id,
            method="POST",
            path="/v1/kiro/chat/completions",
            json_data=request_data
        )
    
    async def chat_completions_stream(
        self,
        user_id: int,
        request_data: Dict[str, Any]
    ):
        """Kiro聊天补全（流式，通过插件API）"""
        async for chunk in self._proxy_stream_request(
            user_id=user_id,
            method="POST",
            path="/v1/kiro/chat/completions",
            json_data=request_data
        ):
            yield chunk