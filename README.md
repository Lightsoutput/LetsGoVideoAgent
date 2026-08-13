# LetsGoVideoAgent

项目结构、运行维护、待办与风险见 [维护文档](docs/MAINTENANCE.md)；本地启动见 [开发指南](docs/LOCAL_DEVELOPMENT.md)；逐接口用途见 [API 中文说明](docs/api/API_GUIDE.md)。

一个通用的多 Agent 视频理解项目，可处理课程、游戏、攻略、访谈和 Vlog 等视频。当前 v1.0 主流程与 Skill Studio 基础能力已完成，后续 v1.1 将重点完善垂类 Skill 对新视频的增强、评测，以及基于 Skill 的视频脚本生成闭环。

## 主要功能

- 上传本地视频或导入网页视频
- 语音识别、OCR、说话人区分
- 自动生成章节和多轨时间轴
- 基于视频内容进行问答，并返回时间戳和画面证据
- 可选联网补充回答，并展示 Search MCP 来源和 Agent 并行工作流
- 生成、修改、发布、绑定、回滚和删除垂类视频 Skill
- v1.1 规划：一句创意 + 垂类 Skill 生成可修改、可评估的视频脚本与分镜
- 支持 DeepSeek 等可替换的 LLM API

## 技术栈

- 前端：Next.js、React、TypeScript
- 后端：Python、FastAPI、Pydantic、LangGraph、自研 Agent Harness
- 视频处理：yt-dlp、PyAV、Faster Whisper、RapidOCR
- 模型与 Agent：DeepSeek、Qwen3-VL、有界 Agentic RAG、多 Agent DAG、SearXNG MCP
- 数据与基础设施：MySQL/Alembic、Docker；Redis、Qdrant、MinIO、Temporal 为可选预留

## 本地启动

推荐在项目根目录双击 `start-all.cmd`，或在 CMD 中执行：

```bat
cd /d G:\2026Summer\LetsGoVideoAgent
start-all.cmd
```

它只在本次手动执行时依次启动 Docker Desktop、SearXNG/Search MCP、后端和前端；
不会注册开机启动或常驻监督器。已运行的服务会自动跳过，日志统一写入 `var/logs/`。

只检查状态而不启动任何服务：

```bat
start-all.cmd -CheckOnly
```

也可以分别启动：

```powershell
# 后端
cd backend
.\.venv\Scripts\python.exe -m uvicorn lets_go_video_agent.main:app --reload

# 前端（新终端）
cd /d G:\2026Summer\LetsGoVideoAgent
npm --prefix frontend run dev
```

打开 `http://localhost:3000`。FastAPI 文档：Swagger `http://localhost:8000/docs`，ReDoc `http://localhost:8000/redoc`，OpenAPI JSON `http://localhost:8000/openapi.json`。

本地上传和网页导入的视频统一保存在项目根目录的 `videos/`。后端启动时会自动扫描并登记该目录中的媒体，已经完成处理的视频及时间轴也会从本地状态目录恢复，因此重启后可直接继续使用，不必重复下载或加载。

缓存、图片和任务资产的命名及保留策略见 [数据生命周期规范](docs/operations/DATA_LIFECYCLE.md)。安全清理默认只预览：`.\scripts\cleanup-data.ps1`；确认后使用 `-Apply`。

视觉理解默认使用硅基流动 `Qwen/Qwen3-VL-32B-Instruct`，本地 Ollama
`qwen3-vl:4b` 可作为离线降级。免费联网检索以 SearXNG MCP Server 提供：

```powershell
.\scripts\start-searxng.ps1
```

MCP 地址为 `http://127.0.0.1:8090/mcp`。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

项目用于本人求职和日常兴趣探索，仅作学习与研究使用。
