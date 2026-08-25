"""Grok 浏览器收割器。

基于实测（见项目记忆 grok-web-api-findings）：
- 会话列表：GET /rest/app-chat/conversations?limit=N&order=updated
- 会话消息：GET /rest/app-chat/conversations/{conversationId}/responses
- 认证：HttpOnly Cookie（无 token 模式），浏览器导航自动携带。

收割策略：Playwright 登录态 -> 页面上下文内 fetch 或直接 page.goto 接口 URL
读取 JSON -> 解析 ChatSession。完全绕开 HttpOnly cookie 问题。
"""
import json
from typing import List, Dict, Any, Optional

from models import ExportConfig, ChatSession, ChatMessage
from exporters.formatter import iso_to_ts
from exporters.browser import BrowserExporter, BrowserError


class GrokBrowserExporter(BrowserExporter):
    """Grok 网页端浏览器收割器"""

    platform = "grok"
    home_url = "https://grok.com/"

    def _login_and_prepare(self, page) -> None:
        page.goto(self.home_url)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)
        try:
            sign_in = page.get_by_role("button", name="Sign in")
            if sign_in.count() > 0:
                self.logger.warning("Grok 未登录，请在打开的浏览器中登录，然后按回车继续...")
                input("按回车继续...")
                page.wait_for_timeout(1000)
        except Exception:
            pass

    def _fetch_json(self, page, path: str) -> Dict[str, Any]:
        """页面上下文内 fetch（自动带 HttpOnly cookie）"""
        return page.evaluate(
            """async (p) => {
                const r = await fetch(p, {credentials: 'include'});
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return await r.json();
            }""",
            path,
        )

    def get_session_ids(self, page) -> List[str]:
        # 从会话列表接口拿全部 conversationId
        conv_ids = []
        offset = 0
        limit = 100
        try:
            while True:
                data = self._fetch_json(
                    page,
                    f"/rest/app-chat/conversations?limit={limit}&offset={offset}&order=updated",
                )
                items = data.get("conversations") or []
                if not items:
                    break
                for it in items:
                    cid = it.get("conversationId")
                    if cid and cid not in conv_ids:
                        conv_ids.append(cid)
                if len(items) < limit:
                    break
                offset += limit
        except Exception as e:
            # 未登录（401/403）或接口异常：返回空，由上层触发登录等待
            self.logger.warning(f"获取会话列表失败（可能是未登录）: {e}")
            return []
        self.logger.info(f"从接口获取 {len(conv_ids)} 个会话")
        return conv_ids

    def _detect_logged_out(self, page) -> bool:
        # 有 Sign in 按钮即未登录
        try:
            sign_in = page.get_by_role("button", name="Sign in")
            if sign_in.count() > 0:
                return True
        except Exception:
            pass
        return True

    def is_logged_in(self, page) -> bool:
        """登录判断：只有接口返回含 conversations 字段才算已登录。

        注意：未登录时接口可能返回 401 JSON，或被重定向到 HTML 登录页
        （<!DOCTYPE...>），这些都不算已登录。
        """
        try:
            # 直接读原始响应，区分 JSON 与 HTML
            raw = page.evaluate(
                """async (p) => {
                    try {
                        const r = await fetch(p, {credentials: 'include'});
                        const text = await r.text();
                        return JSON.stringify({status: r.status, body: text.slice(0, 200)});
                    } catch (e) { return JSON.stringify({status: 0, body: String(e)}); }
                }""",
                "/rest/app-chat/conversations?limit=1&order=updated",
            )
            import json as _json
            info = _json.loads(raw)
            status = info.get("status")
            body = info.get("body", "")
            if status != 200:
                return False
            # 是 JSON 且含 conversations 字段才算登录
            if body.startswith("{"):
                try:
                    data = _json.loads(body)
                    return "conversations" in data
                except Exception:
                    return False
            return False
        except Exception:
            return False

    def iter_session_meta(self):
        """按新到旧返回会话元数据（供增量更新判定停止点）"""
        page = self._get_work_page()
        conv_ids = self.get_session_ids(page)
        metas = []
        for cid in conv_ids:
            ts = None
            try:
                conv = (self._fetch_json(page, f"/rest/app-chat/conversations/{cid}") or {}).get("conversation") or {}
                ts = self._iso_to_ts(conv.get("modifyTime") or conv.get("updateTime"))
            except Exception:
                pass  # 拿不到时间则退化为 ID 判定
            metas.append({"id": cid, "updated_ts": ts})
        return metas

    def fetch_one(self, session_id: str) -> ChatSession:
        """拉取单个会话（含消息），供增量更新使用"""
        page = self._get_work_page()
        return self.fetch_session_detail(page, session_id)

    def fetch_session_detail(self, page, conv_id: str) -> ChatSession:
        # 先拿会话元数据（列表里已有，但直接再查一次稳妥）
        try:
            meta = self._fetch_json(page, f"/rest/app-chat/conversations/{conv_id}")
        except Exception:
            meta = {}
        conv = meta.get("conversation") or meta or {}
        title = conv.get("title") or conv.get("name") or "无标题对话"

        # 拿消息
        data = self._fetch_json(page, f"/rest/app-chat/conversations/{conv_id}/responses")
        responses = data.get("responses") or []

        session = ChatSession(
            id=conv_id,
            title=title,
            create_time=self._iso_to_ts(conv.get("createTime")),
            update_time=self._iso_to_ts(conv.get("modifyTime") or conv.get("updateTime")),
        )
        session.messages = self._parse_responses(responses)
        return session

    @staticmethod
    def _iso_to_ts(value: Optional[str]) -> Optional[int]:
        """兼容别名，公共实现见 exporters.formatter.iso_to_ts"""
        return iso_to_ts(value)

    @staticmethod
    def _parse_responses(responses: List[Dict[str, Any]]) -> List[ChatMessage]:
        """解析 Grok responses 列表。

        真实结构（实测）：扁平列表，每条含 sender 与 message。
          sender=human/assistant/ASSISTANT → 对应角色；message 即正文。
        """
        messages = []
        for resp in responses:
            sender = str(resp.get("sender") or "").lower()
            text = resp.get("message")
            if not text:
                continue
            # sender: human=用户, assistant/ASSISTANT=助手
            if sender == "human":
                role = "user"
            elif sender in ("assistant", "system"):
                role = sender
            else:
                # 无 sender 时根据相邻推断，默认按顺序
                role = "user"
            messages.append(ChatMessage(
                role=role,
                content=str(text).strip(),
                create_time=GrokBrowserExporter._iso_to_ts(resp.get("createTime")),
            ))
        return [m for m in messages if m.content]
