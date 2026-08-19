"""ChatGPT 网页端 HTTP 导出器。

基于实测（见项目记忆 chatgpt-web-api-findings）：
- 会话列表：GET /backend-api/conversations?offset=&limit=&order=updated
- 会话详情：GET /backend-api/conversation/{id}  (mapping 消息树)
- 认证：Authorization: Bearer {accessToken}，token 从 /api/auth/session 获取。
- 网络：chatgpt.com 需经本机 socks5 代理 + curl_cffi Chrome 指纹才能穿透 CF。
  本实现优先使用 requests；若配置了 SOCKS_PROXY 且装有 curl_cffi，则用它。

token 获取策略：
  1) config.bearer_token 若已提供，直接使用；
  2) 否则尝试导航法：GET /api/auth/session 需要 HttpOnly cookie，纯 requests 拿不到，
     所以若用户未提供 token，提示从浏览器取（F12 Network 找 /api/auth/session 的 accessToken）。
"""
from typing import List, Dict, Any, Optional

import requests

from models import ExportConfig, ChatSession, ChatMessage
from exporters.http import HttpExporter, AuthenticationError, HttpError, RateLimitError


class ChatGPTHttpExporter(HttpExporter):
    """ChatGPT 网页端对话导出器"""

    platform = "chatgpt"
    api_base = "https://chatgpt.com/backend-api"

    def _apply_auth(self, config: ExportConfig) -> None:
        self.bearer_token = config.bearer_token.strip()
        # 若配置了 socks 代理，用 curl_cffi Chrome 指纹穿透 CF（实测必需）
        self._proxies = None
        proxy = getattr(config, "socks_proxy", "") or ""
        if proxy:
            # 实测：socks5:// 前缀有效；http:// 前缀会被 CF 拦
            if not proxy.startswith("socks"):
                proxy = "socks5://" + proxy
            self._proxies = {"http": proxy, "https": proxy}
        if self.bearer_token:
            self.session.headers["Authorization"] = f"Bearer {self.bearer_token}"
        # 实测：oai-language 头是 CF 穿透的必要条件之一
        self.session.headers["oai-language"] = "zh-CN"
        # 不设 UA：交给 curl_cffi 的 impersonate=chrome 指纹（自定义 UA 反而 403）

    def close(self) -> None:
        """关闭 HTTP 会话"""
        try:
            if self._creq_session is not None:
                self._creq_session.close()
        except Exception:
            pass
        try:
            self.session.close()
        except Exception:
            pass

    def __init__(self, config: ExportConfig):
        super().__init__(config)
        # curl_cffi 持久 Session：复用连接 + 重试，规避偶发 SSL 断连
        self._creq_session = None
        if self._proxies:
            try:
                from curl_cffi import requests as creq
                self._creq_session = creq.Session(impersonate="chrome", proxies=self._proxies)
            except Exception:
                self._creq_session = None

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """带代理/指纹穿透的请求。配了 socks 代理时用 curl_cffi Chrome 指纹。

        实测（见项目记忆）：`curl_cffi + impersonate=chrome + socks5` + 头
        `oai-language: zh-CN` 才可穿透 CF。首连偶发 SSL 断连，用 Session 重试。

        关键：必须过滤掉 requests.Session 注入的 Python 默认头
        （User-Agent: python-requests/...、Accept: */*、Connection: keep-alive 等），
        否则 CF 据指纹判定为自动化请求返回 403。
        """
        headers = dict(self.session.headers)
        headers.update(kwargs.pop("headers", {}))
        timeout = kwargs.pop("timeout", self.config.timeout)

        if self._creq_session is not None:
            # 过滤 Python 指纹头
            clean = {
                k: v for k, v in headers.items()
                if k.lower() not in ("user-agent", "accept-encoding", "connection", "accept-language")
            }
            last_err = None
            for attempt in range(3):
                try:
                    return self._creq_session.request(method, url, headers=clean, timeout=timeout, **kwargs)
                except Exception as e:
                    last_err = e
                    import time
                    time.sleep(1.5)
            raise HttpError(f"ChatGPT 请求失败（重试 3 次仍被拒/断连）: {last_err}")
        return self.session.request(method, url, headers=headers, timeout=timeout, **kwargs)

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        if endpoint.startswith("http"):
            url = endpoint
        else:
            url = f"{self.api_base}{endpoint}"
        resp = self._request(method, url, **kwargs)
        if resp.status_code == 401:
            raise AuthenticationError("ChatGPT token 无效或已过期")
        if resp.status_code == 429:
            raise RateLimitError("请求过于频繁")
        if resp.status_code >= 500:
            raise HttpError(f"服务器错误: {resp.status_code}")
        if resp.status_code != 200:
            raise HttpError(f"请求失败: {resp.status_code}")
        return resp.json()

    def check_auth(self) -> bool:
        if self._auth_checked:
            return True
        # ChatGPT 无轻量认证检查接口稳定可用；用 conversations?limit=1 探测
        try:
            self._make_request("GET", "/conversations?offset=0&limit=1&order=updated")
            self.logger.info("认证成功")
            self._auth_checked = True
            return True
        except AuthenticationError as e:
            self.logger.error(f"认证失败: {e}")
            return False
        except HttpError as e:
            self.logger.error(f"认证检查失败: {e}")
            return False

    def get_chat_list_raw(self, offset: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """获取会话列表原始数据"""
        data = self._make_request(
            "GET",
            f"/conversations?offset={offset}&limit={limit}&order=updated",
        )
        return data.get("items", [])

    def get_chat_detail_raw(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """获取会话详情（mapping 消息树），429 时指数退避重试"""
        import time as _time
        delays = [5, 10, 20]
        for attempt in range(4):
            try:
                return self._make_request("GET", f"/conversation/{conversation_id}")
            except RateLimitError:
                if attempt < 3:
                    self.logger.warning(
                        f"获取会话 {conversation_id} 触发限频，等待 {delays[attempt]} 秒重试..."
                    )
                    _time.sleep(delays[attempt])
                    continue
                self.logger.warning(f"获取会话 {conversation_id} 详情持续限频，放弃")
                return None
            except HttpError as e:
                self.logger.warning(f"获取会话 {conversation_id} 详情失败: {e}")
                return None
        return None

    def parse_chat_session(self, item: Dict[str, Any]) -> ChatSession:
        """从列表项解析 ChatSession"""
        create_time = item.get("create_time")
        update_time = item.get("update_time")
        # ChatGPT 时间是 ISO 字符串，转秒时间戳
        create_ts = self._iso_to_ts(create_time)
        update_ts = self._iso_to_ts(update_time)
        return ChatSession(
            id=item.get("id", ""),
            title=item.get("title", "无标题对话"),
            create_time=create_ts,
            update_time=update_ts,
        )

    @staticmethod
    def _iso_to_ts(value: Optional[str]) -> Optional[int]:
        """把 ISO 时间字符串转秒时间戳（如 2026-08-17T05:55:44.370119Z）"""
        if not value:
            return None
        try:
            from datetime import datetime
            # 处理末尾 Z 与微秒
            v = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(v)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            return None

    def parse_messages(self, detail: Dict[str, Any]) -> List[ChatMessage]:
        """从会话详情 mapping 提取消息。

        只保留 user/assistant 的纯文本消息，过滤工具调用（role=tool / content 非 text）。
        """
        messages: List[ChatMessage] = []
        mapping = detail.get("mapping", {}) or {}
        nodes = []
        for node in mapping.values():
            if not node:
                continue
            msg = node.get("message")
            if not msg:
                continue
            role = msg.get("author", {}).get("role", "unknown")
            # 只保留 user / assistant 对话消息
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content") or {}
            content_type = content.get("content_type")
            # 只要纯文本内容（跳过 tool 调用、code 等非 text 类型）
            if content_type not in (None, "text"):
                continue
            parts = content.get("parts") or []
            texts = [p for p in parts if isinstance(p, str) and p.strip()]
            if not texts:
                continue
            create_time = msg.get("create_time")
            nodes.append(ChatMessage(
                role=role,
                content="\n".join(texts).strip(),
                create_time=create_time,
            ))
        nodes.sort(key=lambda m: m.create_time or 0)
        return [m for m in nodes if m.content]

    def fetch_all_chats(self) -> List[ChatSession]:
        """拉取全量会话（含消息）"""
        all_sessions = []
        offset = 0
        limit = 100
        while True:
            items = self.get_chat_list_raw(offset=offset, limit=limit)
            if not items:
                break
            for item in items:
                session = self.parse_chat_session(item)
                detail = self.get_chat_detail_raw(session.id)
                if not detail:
                    self.logger.warning(f"  跳过（无法获取详情）: {session.title}")
                    continue
                msgs = self.parse_messages(detail)
                if not msgs:
                    self.logger.warning(f"  跳过（无消息内容）: {session.title}")
                    continue
                session.messages = msgs
                all_sessions.append(session)
                self.logger.info(f"  已加载: {session.title} ({len(msgs)} 条消息)")
            if len(items) < limit:
                break
            offset += limit
        self.logger.info(f"共获取到 {len(all_sessions)} 条对话")
        return all_sessions
