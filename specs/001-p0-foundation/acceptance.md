# Spec 001 验收清单

## 自动门禁

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff format --check src tests migrations
.\.venv\Scripts\python.exe -m ruff check src tests migrations
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m lets_go_video_agent.evaluation.cli

cd ..\frontend
pnpm lint
pnpm typecheck
pnpm test
pnpm build
$env:E2E_EXTERNAL_SERVER='1'
.\node_modules\.bin\playwright.CMD test --reporter=line
```

## 功能验收

- [x] 合成视频不依赖第三方媒体或付费 API。
- [x] 四类问题均返回结构化引用和 Trace ID。
- [x] 当前帧回答包含可加载截图和可跳转时间戳。
- [x] 工具越权、重复循环和预算超限有拒绝路径。
- [x] 远程下载默认关闭，未确认权利不下载。
- [x] 生产适配器可导入，并有无真实外部服务合约测试。
- [ ] Docker Compose 真实启动验收（当前主机无 Docker CLI）。
- [ ] 真实视频 ASR/OCR/VLM 质量验收。

本 Spec 通过时只能对外称为 **P0 Foundation**。完成 `tasks.md` 的
真实视频任务并通过三类授权视频评测后，才可称为“1.0 P0 完整版”。
