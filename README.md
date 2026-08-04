# LetsGoVideoAgent

一个通用的多 Agent 视频理解项目，可处理课程、游戏、攻略、访谈和 Vlog 等视频。

## 主要功能

- 上传本地视频或导入网页视频
- 语音识别、OCR、说话人区分
- 自动生成章节和多轨时间轴
- 基于视频内容进行问答，并返回时间戳和画面证据
- 支持 DeepSeek 等可替换的 LLM API

## 技术栈

- 前端：Next.js、React、TypeScript
- 后端：Python、FastAPI、LangGraph
- 视频处理：yt-dlp、PyAV、Faster Whisper、RapidOCR
- 数据与基础设施：MySQL、Redis、Qdrant、MinIO、Docker

## 本地启动

```powershell
# 后端
cd backend
.\.venv\Scripts\python.exe -m uvicorn lets_go_video_agent.main:app --reload

# 前端（新终端）
cd /d G:\2026Summer\LetsGoVideoAgent
npm --prefix frontend run dev
```

打开 `http://localhost:3000`，API 文档位于 `http://localhost:8000/docs`。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

项目目前处于 V1.0 P0 阶段，用于本人求职和日常兴趣探索，该项目仅用于学习、研究作用。
