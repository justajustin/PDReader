# 贡献指南

欢迎改进 PDReader 的文件兼容性、学习体验和文档。请先阅读 [README](README.md) 了解客户端与可选平台的范围。

## 本地开发

在 Windows 上按 README 创建虚拟环境并安装 `.[dev]`，从仓库目录执行 `python -m ppt_study`。建议在开发终端设置 `PPT_STUDY_DISABLE_PLATFORM=1`，避免开发操作发送到平台。

- `src/ppt_study/app.py`：桌面窗口与资源准备。
- `api.py`：Python 与前端之间的桥接。
- `ingest.py`、`export_*`、`extract_*`：课件解析、页面渲染和媒体提取。
- `context.py`、`ai_client.py`：模型上下文与接口适配。
- `billing_client.py`、`billing_config.py`：可选远程平台客户端。
- `web/`：无前端构建步骤的 HTML、CSS、JavaScript。
- `tests/`：客户端测试，不依赖私有运营后台。
- `scripts/`、`PDReader*.spec`：Windows 打包。

## 提交修改

1. 新建分支，围绕一个具体问题修改。
2. 运行 `.\.venv\Scripts\python.exe -m pytest -q`；修改解析或请求行为时补充针对性的回归测试。
3. 修改界面后在真实客户端检查布局、公式和主题；不要仅凭字符串断言判断视觉正确。
4. PR 描述写明问题、变化及验证结果。涉及文件兼容性时使用可以公开分享的最小样例。

不要提交 `.venv`、安装包、运行日志、个人课件、用户数据、服务端配置或密钥。第三方资源需注明来源并保留许可证。提交贡献即表示你同意以本项目的 MIT 许可提供该贡献。

## 测试边界

自动化测试使用临时目录及模拟接口，不能替代真实 Office / WPS、WebView2、第三方模型接口与安装器的端到端验证。只有实际完成的验证才能在 PR 中标为通过。
