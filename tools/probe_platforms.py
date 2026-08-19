"""
无凭证探测脚本：验证各平台网页接口的防护层
只回答三个问题（不需要任何登录凭证）：
  1. 普通 requests 能否触达接口（是否被 Cloudflare/TLS 指纹拦截）
  2. 接口是否存在（404 vs 401/403）
  3. 未认证时返回什么（认证方式线索：是否需要 Bearer/Cookie/签名）

用法:
    python tools/probe_platforms.py            # 探测全部平台
    python tools/probe_platforms.py chatgpt    # 只探测一个平台
"""
import sys
import time
import requests

# 与 deepseek_export.py 保持一致的浏览器 UA
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0")

BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    # 不带 Accept-Encoding: gzip/br，避免手工解压干扰；让 requests 自动处理
}

# 每个平台探测的端点：会话列表接口是导出工具的核心依赖
PROBES = {
    "deepseek": [
        ("GET", "https://chat.deepseek.com/api/v0/chat_session/fetch_page", None, {}),
        ("GET", "https://chat.deepseek.com/api/v0/client/settings?scope=model", None, {}),
    ],
    "chatgpt": [
        # 会话列表（backend-api 是网页版真实接口）
        ("GET", "https://chatgpt.com/backend-api/conversations?offset=0&limit=1", None, {}),
        # 免认证的 session 端点（网页启动时调用，用于观察防护层）
        ("GET", "https://chatgpt.com/backend-api/models", None, {}),
        ("GET", "https://auth.openai.com/.well-known/openid-configuration", None, {}),
    ],
    "qwen": [
        # 国际版 Qwen Chat
        ("GET", "https://chat.qwen.ai/chat/list", None, {}),
        ("GET", "https://chat.qwen.ai/api/chat/list", None, {}),
        # 国内版通义
        ("GET", "https://www.tongyi.com/chat/list", None, {}),
        ("POST", "https://www.tongyi.com/api/v1/chatapi/chats/page-fetch", None, {"page": 1, "pageSize": 10}),
    ],
    "grok": [
        ("GET", "https://grok.com/rest/app-chat/conversations.new", None, {}),
        ("GET", "https://grok.com/rest/app-chat/conversations", None, {}),
        ("GET", "https://grok.com/rest/app-chat/rate-limits", None, {}),
    ],
    "doubao": [
        # 豆包网页版（字节系）
        ("GET", "https://www.doubao.com/samantha/chat/list", None, {}),
        ("POST", "https://www.doubao.com/samantha/chat/list", None, {}),
        ("GET", "https://www.doubao.com/algo2/v1/samantha/chat/list", None, {}),
        ("GET", "https://www.doubao.com/passport/account/info/v2/", None, {}),
    ],
}


def probe_one(name, method, url, body, extra_headers):
    headers = dict(BASE_HEADERS)
    headers.update(extra_headers)
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        t0 = time.time()
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=15)
        else:
            r = requests.post(url, headers=headers, json=body, timeout=15)
        elapsed = time.time() - t0

        # 判定防护层特征
        server = r.headers.get("server", "")
        cf_ray = "Cloudflare" if r.headers.get("cf-ray") else ""
        cf_mitigated = "CF挑战页" if r.headers.get("cf-mitigated") else ""
        protected_by = [x for x in (server, cf_ray, cf_mitigated) if x]

        body_snippet = ""
        try:
            body_snippet = r.text[:200].replace("\n", " ")
        except Exception:
            pass

        print(f"  [{r.status_code}] {method} {url}")
        print(f"        server={server or '?'}  cf-ray={'有' if r.headers.get('cf-ray') else '无'}  "
              f"耗时={elapsed:.1f}s  长度={len(r.content)}")
        print(f"        body: {body_snippet}")
        return r
    except requests.exceptions.RequestException as e:
        print(f"  [网络错误] {method} {url}")
        print(f"        {type(e).__name__}: {str(e)[:150]}")
        return None


def main():
    targets = sys.argv[1:] or list(PROBES.keys())
    for name in targets:
        if name not in PROBES:
            print(f"未知平台: {name}，可选: {', '.join(PROBES)}")
            continue
        print(f"\n{'='*60}\n平台: {name}\n{'='*60}")
        for method, url, body, extra in PROBES[name]:
            probe_one(name, method, url, body, extra)
            time.sleep(1.0)  # 礼貌间隔


if __name__ == "__main__":
    main()
