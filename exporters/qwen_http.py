"""千问（Qwen）HTTP 导出器。

基于实测（见项目记忆 qianwen-web-api-findings）：
- 网关与主站分离：会话接口在 chat2-api.qianwen.com（CHAT_NA 网关）
- 会话列表：POST /api/v2/session/page/list
- 消息列表：GET /api/v1/session/msg/list?session_id={id}
- 认证：query 参数 ut（UC 加密令牌，真实值需 F12 Network Copy as cURL 获取）
  必带头：X-Platform: pc_tongyi、X-XSRF-TOKEN（Cookie 同名值）、Origin/Referer。

注意：ut 无效时接口返回 200 但 data 为空（按匿名处理）。用户必须提供真实 ut。
"""
from typing import List, Dict, Any, Optional

from models import ExportConfig, ChatSession, ChatMessage
from exporters.formatter import normalize_ts
from exporters.http import HttpExporter, AuthenticationError, HttpError, RateLimitError

GATEWAY = "https://chat2-api.qianwen.com"


class QwenHttpExporter(HttpExporter):
    """千问网页端 HTTP 导出器"""

    platform = "qwen"
    api_base = GATEWAY

    def _apply_auth(self, config: ExportConfig) -> None:
        self.cookie = config.cookie.strip()
        self.ut = config.ut.strip()
        # XSRF-TOKEN 从 cookie 里取
        self.xsrf = ""
        for part in self.cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "XSRF-TOKEN":
                self.xsrf = v
        if self.cookie:
            self.session.headers["Cookie"] = self.cookie
        if self.xsrf:
            self.session.headers["X-XSRF-TOKEN"] = self.xsrf
        self.session.headers["X-Platform"] = "pc_tongyi"
        self.session.headers["Origin"] = "https://www.qianwen.com"
        self.session.headers["Referer"] = "https://www.qianwen.com/"

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        # 千问所有请求都要带 ut 参数（query）
        params = dict(kwargs.pop("params", {}) or {})
        params.setdefault("ut", self.ut or "1")
        return super()._make_request(method, endpoint, params=params, **kwargs)

    def check_auth(self) -> bool:
        if self._auth_checked:
            return True
        try:
            data = self._make_request(
                "POST", "/api/v2/session/page/list",
                json={"pageSize": 1, "page": 1},
            )
            # data 非空说明 ut 有效
            if data.get("code") == 0 and data.get("data"):
                self.logger.info("认证成功")
                self._auth_checked = True
                return True
            self.logger.warning("ut 无效（接口返回空数据，需从 F12 获取真实 ut）")
            return False
        except AuthenticationError as e:
            self.logger.error(f"认证失败: {e}")
            return False
        except HttpError as e:
            self.logger.error(f"认证检查失败: {e}")
            return False

    def get_chat_list_raw(self, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        data = self._make_request(
            "POST", "/api/v2/session/page/list",
            json={"pageSize": page_size, "page": page, "biz_id": "ai_qwen"},
        )
        return data.get("data") or {}

    def get_chat_detail_raw(self, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._make_request(
                "GET", "/api/v1/session/msg/list",
                params={"session_id": session_id, "biz_id": "ai_qwen",
                        "chat_client": "h5", "device": "pc", "fr": "pc",
                        "pr": "qwen", "la": "zh-CN", "tz": "Asia/Shanghai"},
            )
        except HttpError as e:
            self.logger.warning(f"获取会话 {session_id} 详情失败: {e}")
            return None

    def parse_chat_session(self, item: Dict[str, Any]) -> ChatSession:
        create_ts = self._ts(item.get("created_at"))
        update_ts = self._ts(item.get("last_req_timestamp"))
        return ChatSession(
            id=item.get("session_id", ""),
            title=item.get("title", "无标题对话"),
            create_time=create_ts,
            update_time=update_ts,
        )

    @staticmethod
    def _ts(value) -> Optional[int]:
        """兼容别名，公共实现见 exporters.formatter.normalize_ts"""
        return normalize_ts(value)

    def parse_messages(self, detail: Dict[str, Any]) -> List[ChatMessage]:
        messages = []
        # 千问 msg/list 返回结构：data.list[].content（可能是分块）
        data = detail.get("data") or {}
        items = data.get("list") or []
        for m in items:
            role = m.get("role") or ("user" if m.get("is_user") else "assistant")
            content = self._extract_content(m)
            if not content:
                continue
            messages.append(ChatMessage(
                role=str(role).lower(),
                content=content,
                create_time=self._ts(m.get("created_at") or m.get("create_time")),
            ))
        return messages

    @staticmethod
    def _extract_content(m: Dict[str, Any]) -> str:
        content = m.get("content")
        if isinstance(content, str):
            return content.strip()
        # 分块 content: [{content_type:"text", text:...}]
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, dict):
                    parts.append(c.get("text") or c.get("content") or "")
            return "\n".join(p for p in parts if p).strip()
        return ""

    def iter_session_meta(self):
        """按新到旧返回会话元数据（供增量更新）；顺带缓存列表项供 fetch_one 补标题"""
        self._meta_cache = {}
        metas = []
        page = 1
        while True:
            data = self.get_chat_list_raw(page=page)
            items = data.get("list") or []
            if not items:
                break
            for item in items:
                sid = item.get("session_id", "")
                if not sid:
                    continue
                self._meta_cache[sid] = item
                ts = self._ts(item.get("last_req_timestamp") or item.get("created_at"))
                metas.append({"id": sid, "updated_ts": ts})
            next_token = data.get("next_token")
            if not next_token or len(items) < 50:
                break
            page += 1
        return metas

    def fetch_one(self, session_id: str) -> Optional[ChatSession]:
        """拉取单个会话（含消息），标题从 iter_session_meta 的缓存取"""
        item = getattr(self, "_meta_cache", {}).get(session_id, {"session_id": session_id})
        session = self.parse_chat_session(item)
        detail = self.get_chat_detail_raw(session_id)
        if not detail:
            return None
        msgs = self.parse_messages(detail)
        if not msgs:
            return None
        session.messages = msgs
        return session

    def fetch_all_chats(self) -> List[ChatSession]:
        all_sessions = []
        page = 1
        while True:
            data = self.get_chat_list_raw(page=page)
            items = data.get("list") or []
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
            next_token = data.get("next_token")
            if not next_token or len(items) < 50:
                break
            page += 1
        self.logger.info(f"共获取到 {len(all_sessions)} 条对话")
        return all_sessions
