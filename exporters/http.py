"""HttpExporter：HTTP 重放引擎基类。

封装统一的 requests 会话、认证注入、状态码/业务错误码处理。
子类提供 API_BASE 与 headers 模板即可。
"""
import json
import time
from typing import Dict, Any, Optional

import requests

from models import ExportConfig
from exporters.base import BaseExporter


class HttpError(Exception):
    """HTTP 引擎通用错误"""
    pass


class AuthenticationError(HttpError):
    """认证错误"""
    pass


class RateLimitError(HttpError):
    """频率限制错误"""
    pass


class HttpExporter(BaseExporter):
    """基于 requests 的导出器基类"""

    # 子类覆盖
    api_base: str = ""
    headers_template: Dict[str, str] = {}

    def __init__(self, config: ExportConfig):
        super().__init__(config)
        self.session = requests.Session()
        self.session.headers.update(self.headers_template)
        self._apply_auth(config)
        self._auth_checked = False

    def _apply_auth(self, config: ExportConfig) -> None:
        """子类覆盖：把凭证注入 session（cookie / bearer / ut / 自定义头）"""
        raise NotImplementedError

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送请求并统一处理错误。

        注意：endpoint 可以是绝对 URL（含协议）或相对路径（拼接 api_base）。
        """
        if endpoint.startswith("http"):
            url = endpoint
        else:
            url = f"{self.api_base}{endpoint}"

        try:
            response = self.session.request(
                method=method, url=url, timeout=self.config.timeout, **kwargs
            )
        except requests.exceptions.Timeout:
            raise HttpError(f"请求超时 ({self.config.timeout}秒)")
        except requests.exceptions.RequestException as e:
            raise HttpError(f"网络请求失败: {e}")

        # 状态码处理
        if response.status_code == 401:
            raise AuthenticationError("认证无效或已过期")
        if response.status_code == 429:
            raise RateLimitError("请求过于频繁，请稍后再试")
        if response.status_code >= 500:
            raise HttpError(f"服务器错误: {response.status_code}")
        if response.status_code != 200:
            raise HttpError(f"请求失败: {response.status_code}")

        # JSON 解析
        try:
            return response.json()
        except json.JSONDecodeError:
            raise HttpError("响应不是有效 JSON")

    def check_auth(self) -> bool:
        """子类覆盖：各平台认证检查方式不同"""
        raise NotImplementedError

    def fetch_all_chats(self):
        """子类覆盖：拉取全量会话"""
        raise NotImplementedError

    def close(self) -> None:
        """关闭 HTTP 会话"""
        try:
            self.session.close()
        except Exception:
            pass
