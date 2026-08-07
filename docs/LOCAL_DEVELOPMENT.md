# 本地开发启动

在项目根目录打开两个终端。

后端：

```powershell
backend\.venv\Scripts\python.exe -m uvicorn lets_go_video_agent.main:app `
  --host 127.0.0.1 --port 8000
```

前端：

```powershell
pnpm --dir frontend dev
```

如果系统没有全局 pnpm，可先运行 `corepack enable`，或者使用项目 README 中记录的依赖安装方式。启动前应先检查 8000 和 3000 端口，避免重复运行服务。

本地基础设施：

```powershell
.\scripts\start-searxng.ps1
```

运行日志统一写入 `var/logs/<service>/`，不要输出到项目根目录。
