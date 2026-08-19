# DeepSeek 对话手动导出指南

由于 Cookie 认证失败，以下是替代方案。

> 本项目已内置自动化导出能力：DeepSeek 走 HTTP 重放（需 Cookie/Token，见「方案四」），
> 千问 / 豆包 / Grok 支持浏览器收割引擎（打开浏览器登录后自动导出，无需手动复制 Cookie），
> 但 DeepSeek 暂未提供浏览器引擎。

## 方案一：使用浏览器扩展（推荐）

1. 安装 **DeepSeek Chat Exporter** 浏览器扩展
   - Chrome 商店搜索 "DeepSeek Chat Exporter"
   - 或访问：https://chromewebstore.google.com/detail/deepseek-chat-exporter

2. 在 chat.deepseek.com 页面点击扩展图标
3. 选择导出格式（Markdown/JSON/HTML）
4. 保存文件

## 方案二：手动复制（简单）

1. 打开 https://chat.deepseek.com
2. 进入需要导出的对话
3. 逐条复制对话内容
4. 粘贴到 Markdown 文件中

## 方案三：使用仓库内置的自动化（其他平台，千问/豆包/Grok）

仓库内置 Playwright 浏览器收割引擎（`exporters/browser.py`），适用于认证依赖
HttpOnly Cookie 或动态签名的平台（千问 / 豆包 / Grok），登录一次后写入本地
profile（`~/.web_chat_export/profiles/{platform}`），下次免登录：

```bash
pip install -r requirements.txt
playwright install chromium

python deepseek_export.py --platform qwen --engine browser --all
python deepseek_export.py --platform doubao --engine browser --all
python deepseek_export.py --platform grok --engine browser --all
```

> 注意：DeepSeek 平台目前只有 HTTP 引擎（`--engine browser` 会被忽略），
> 其自动导出需要 Cookie + Bearer Token，见「方案四」。

您的 Cookie 可能已过期，请重新获取：

1. 打开 https://chat.deepseek.com 并登录
2. 按 F12 → Network 标签
3. 刷新页面
4. 找到任意请求，复制最新的 Cookie
5. 更新 .env 文件
6. 运行自动导出：
   ```bash
   python deepseek_export.py --platform deepseek --all
   ```

---

**注意**：由于 DeepSeek 的安全机制，API 方式的 Cookie 有效期很短。建议：
- 使用浏览器扩展（最稳定，免维护）
- 或定期更新 Cookie 后使用 HTTP 重放自动导出
