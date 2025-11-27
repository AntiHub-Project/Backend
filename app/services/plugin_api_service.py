"""
Plug-in API服务
处理与plug-in-api系统的通信
"""
from typing import Optional, Dict, Any, List
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.plugin_api_key_repository import PluginAPIKeyRepository
from app.utils.encryption import encrypt_api_key, decrypt_api_key
from app.schemas.plugin_api import (
    PluginAPIKeyCreate,
    PluginAPIKeyResponse,
    CreatePluginUserRequest,
)


class PluginAPIService:
    """Plug-in API服务类"""
    
    def __init__(self, db: AsyncSession):
        """
        初始化服务
        
        Args:
            db: 数据库会话
        """
        self.db = db
        self.settings = get_settings()
        self.repo = PluginAPIKeyRepository(db)
        self.base_url = self.settings.plugin_api_base_url
        self.admin_key = self.settings.plugin_api_admin_key
    
    # ==================== 密钥管理 ====================
    
    async def save_user_api_key(
        self,
        user_id: int,
        api_key: str,
        plugin_user_id: Optional[str] = None
    ) -> PluginAPIKeyResponse:
        """
        保存用户的plug-in API密钥
        
        Args:
            user_id: 用户ID
            api_key: 用户的plug-in API密钥
            plugin_user_id: plug-in系统中的用户ID
            
        Returns:
            保存的密钥信息
        """
        # 加密API密钥
        encrypted_key = encrypt_api_key(api_key)
        
        # 检查是否已存在
        existing = await self.repo.get_by_user_id(user_id)
        
        if existing:
            # 更新现有密钥
            updated = await self.repo.update(
                user_id=user_id,
                api_key=encrypted_key,
                plugin_user_id=plugin_user_id
            )
            return PluginAPIKeyResponse.model_validate(updated)
        else:
            # 创建新密钥
            created = await self.repo.create(
                user_id=user_id,
                api_key=encrypted_key,
                plugin_user_id=plugin_user_id
            )
            return PluginAPIKeyResponse.model_validate(created)
    
    async def get_user_api_key(self, user_id: int) -> Optional[str]:
        """
        获取用户的解密后的API密钥
        
        Args:
            user_id: 用户ID
            
        Returns:
            解密后的API密钥，不存在返回None
        """
        key_record = await self.repo.get_by_user_id(user_id)
        if not key_record or not key_record.is_active:
            return None
        
        # 解密并返回
        return decrypt_api_key(key_record.api_key)
    
    async def delete_user_api_key(self, user_id: int) -> bool:
        """
        删除用户的API密钥
        
        Args:
            user_id: 用户ID
            
        Returns:
            删除成功返回True
        """
        return await self.repo.delete(user_id)
    
    async def update_last_used(self, user_id: int):
        """更新密钥最后使用时间"""
        await self.repo.update_last_used(user_id)
    
    # ==================== Plug-in API代理方法 ====================
    
    async def create_plugin_user(
        self,
        request: CreatePluginUserRequest
    ) -> Dict[str, Any]:
        """
        创建plug-in-api用户（管理员操作）
        
        Args:
            request: 创建用户请求
            
        Returns:
            创建结果，包含用户信息和API密钥
        """
        url = f"{self.base_url}/api/users"
        payload = request.model_dump()
        headers = {"Authorization": f"Bearer {self.admin_key}"}
        
        # 打印请求详情
        print(f"📤 发送创建plug-in用户请求:")
        print(f"   URL: POST {url}")
        print(f"   Headers: {headers}")
        print(f"   Payload: {payload}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
                timeout=30.0
            )
            
            # 打印响应详情
            print(f"📥 收到plug-in-api响应:")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text}")
            
            response.raise_for_status()
            return response.json()
    
    async def auto_create_and_bind_plugin_user(
        self,
        user_id: int,
        username: str,
        prefer_shared: int = 0
    ) -> PluginAPIKeyResponse:
        """
        自动创建plug-in-api用户并绑定到我们的用户
        
        Args:
            user_id: 我们系统中的用户ID
            username: 用户名
            prefer_shared: Cookie优先级，0=专属优先，1=共享优先
            
        Returns:
            保存的密钥信息
        """
        # 创建plug-in-api用户
        request = CreatePluginUserRequest(
            name=username,
            prefer_shared=prefer_shared
        )
        
        result = await self.create_plugin_user(request)
        
        # 提取API密钥和用户ID
        api_key = result.get("data", {}).get("api_key")
        plugin_user_id = result.get("data", {}).get("user_id")
        
        if not api_key:
            raise ValueError("创建plug-in用户失败：未返回API密钥")
        
        # 保存密钥到我们的数据库
        return await self.save_user_api_key(
            user_id=user_id,
            api_key=api_key,
            plugin_user_id=plugin_user_id
        )
    
    async def proxy_request(
        self,
        user_id: int,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        代理用户请求到plug-in-api
        
        Args:
            user_id: 用户ID
            method: HTTP方法
            path: API路径
            json_data: JSON请求体
            params: 查询参数
            extra_headers: 额外的请求头
            
        Returns:
            API响应
        """
        # 获取用户的API密钥
        api_key = await self.get_user_api_key(user_id)
        if not api_key:
            raise ValueError("用户未配置plug-in API密钥")
        
        # 更新最后使用时间
        await self.update_last_used(user_id)
        
        # 发送请求
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        # 添加额外的请求头
        if extra_headers:
            headers.update(extra_headers)
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=headers,
                timeout=300.0
            )
            response.raise_for_status()
            return response.json()
    
    async def proxy_stream_request(
        self,
        user_id: int,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None
    ):
        """
        代理流式请求到plug-in-api
        
        Args:
            user_id: 用户ID
            method: HTTP方法
            path: API路径
            json_data: JSON请求体
            extra_headers: 额外的请求头
            
        Yields:
            流式响应数据
        """
        # 获取用户的API密钥
        api_key = await self.get_user_api_key(user_id)
        if not api_key:
            raise ValueError("用户未配置plug-in API密钥")
        
        # 更新最后使用时间
        await self.update_last_used(user_id)
        
        # 发送流式请求
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        # 添加额外的请求头
        if extra_headers:
            headers.update(extra_headers)
        
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
    
    # ==================== 具体API方法 ====================
    
    async def get_oauth_authorize_url(
        self,
        user_id: int,
        is_shared: int = 0
    ) -> Dict[str, Any]:
        """获取OAuth授权URL"""
        return await self.proxy_request(
            user_id=user_id,
            method="POST",
            path="/api/oauth/authorize",
            json_data={
                "is_shared": is_shared
            }
        )
    
    async def submit_oauth_callback(
        self,
        user_id: int,
        callback_url: str
    ) -> Dict[str, Any]:
        """提交OAuth回调"""
        return await self.proxy_request(
            user_id=user_id,
            method="POST",
            path="/api/oauth/callback/manual",
            json_data={"callback_url": callback_url}
        )
    
    async def get_accounts(self, user_id: int) -> Dict[str, Any]:
        """获取账号列表"""
        return await self.proxy_request(
            user_id=user_id,
            method="GET",
            path="/api/accounts"
        )
    
    async def get_account(self, user_id: int, cookie_id: str) -> Dict[str, Any]:
        """获取单个账号信息"""
        return await self.proxy_request(
            user_id=user_id,
            method="GET",
            path=f"/api/accounts/{cookie_id}"
        )
    
    async def update_account_status(
        self,
        user_id: int,
        cookie_id: str,
        status: int
    ) -> Dict[str, Any]:
        """更新账号状态"""
        return await self.proxy_request(
            user_id=user_id,
            method="PUT",
            path=f"/api/accounts/{cookie_id}/status",
            json_data={"status": status}
        )
    
    async def delete_account(
        self,
        user_id: int,
        cookie_id: str
    ) -> Dict[str, Any]:
        """删除账号"""
        return await self.proxy_request(
            user_id=user_id,
            method="DELETE",
            path=f"/api/accounts/{cookie_id}"
        )
    
    async def get_account_quotas(
        self,
        user_id: int,
        cookie_id: str
    ) -> Dict[str, Any]:
        """获取账号配额信息"""
        return await self.proxy_request(
            user_id=user_id,
            method="GET",
            path=f"/api/accounts/{cookie_id}/quotas"
        )
    
    async def get_user_quotas(self, user_id: int) -> Dict[str, Any]:
        """获取用户共享配额池"""
        return await self.proxy_request(
            user_id=user_id,
            method="GET",
            path="/api/quotas/user"
        )
    
    async def get_shared_pool_quotas(self, user_id: int) -> Dict[str, Any]:
        """获取共享池配额"""
        return await self.proxy_request(
            user_id=user_id,
            method="GET",
            path="/api/quotas/shared-pool"
        )
    
    async def get_quota_consumption(
        self,
        user_id: int,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取配额消耗记录"""
        params = {}
        if limit:
            params["limit"] = limit
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        
        return await self.proxy_request(
            user_id=user_id,
            method="GET",
            path="/api/quotas/consumption",
            params=params
        )
    
    async def get_models(self, user_id: int, config_type: Optional[str] = None) -> Dict[str, Any]:
        """获取可用模型列表"""
        extra_headers = {}
        if config_type:
            extra_headers["X-Account-Type"] = config_type
        print(f"Using config_type header: {config_type}")
        
        return await self.proxy_request(
            user_id=user_id,
            method="GET",
            path="/v1/models",
            extra_headers=extra_headers if extra_headers else None
        )
    
    async def update_cookie_preference(
        self,
        user_id: int,
        plugin_user_id: str,
        prefer_shared: int
    ) -> Dict[str, Any]:
        """更新Cookie优先级"""
        return await self.proxy_request(
            user_id=user_id,
            method="PUT",
            path=f"/api/users/{plugin_user_id}/preference",
            json_data={"prefer_shared": prefer_shared}
        )
    
    async def get_user_info(self, user_id: int) -> Dict[str, Any]:
        """获取用户信息"""
        return await self.proxy_request(
            user_id=user_id,
            method="GET",
            path="/api/user/me"
        )
    
    async def update_model_quota_status(
        self,
        user_id: int,
        cookie_id: str,
        model_name: str,
        status: int
    ) -> Dict[str, Any]:
        """更新模型配额状态"""
        return await self.proxy_request(
            user_id=user_id,
            method="PUT",
            path=f"/api/accounts/{cookie_id}/quotas/{model_name}/status",
            json_data={"status": status}
        )