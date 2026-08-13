# LetsGoVideoAgent API 中文说明

> 对应仓库 OpenAPI 快照：2026-08-13，共 37 条路由。  
> 本文解释接口“用来做什么”；字段的最终约束以运行中的 OpenAPI 为准。

## 1. 查看与更新接口文档

启动后端后可直接查看：

- Swagger（适合直接试接口）：`http://127.0.0.1:8000/docs`
- ReDoc（适合连续阅读）：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`
- API 前缀：`http://127.0.0.1:8000/api/v1`

仓库中的静态快照为 `docs/api/openapi.json`。路由或 Pydantic Schema 改动后执行：

```powershell
backend\.venv\Scripts\python.exe scripts\export-openapi.py
```

## 2. 通用约定

- JSON 请求使用 `Content-Type: application/json`，上传接口使用 `multipart/form-data`。
- 视频、项目、Skill、Run 和 Trace 的标识通常是 UUID。
- 时间统一使用整数毫秒；例如 `297000` 表示 `04:57.000`，不要传浮点数。
- 视频处理是异步任务：启动接口返回后，应轮询处理状态和 Agent Trace，而不是让 HTTP 请求一直等待。
- 业务错误使用 `application/problem+json`；`422` 通常表示请求字段或类型不合法。
- 当前是本地个人版，尚未提供完整登录/RBAC；暴露到公网前必须增加鉴权、限流和上传安全策略。

## 3. 健康检查

| 方法与路径 | 用途 |
| --- | --- |
| `GET /health/live` | 判断 FastAPI 进程是否存活。只回答“进程活着”，不保证外部依赖可用。 |
| `GET /health/ready` | 检查后端是否已准备接收业务请求，并返回关键依赖状态。启动脚本应优先使用它。 |

## 4. 视频接入与处理

| 方法与路径 | 用途 | 关键输入/输出 |
| --- | --- | --- |
| `GET /videos` | 获取视频库，用于左侧列表和恢复上次任务。 | 返回视频列表及处理状态。 |
| `GET /videos/{video_id}` | 获取单个视频元数据。 | `video_id`；返回标题、时长、来源和状态。 |
| `POST /videos/uploads` | 上传本地视频。 | 表单字段 `file`，支持 MP4/MOV/MKV/WebM。 |
| `POST /videos/imports` | 登记并异步下载网页视频。 | `url`、可选 `title`、`rights_confirmed`。 |
| `POST /videos/{video_id}/processing` | 启动或重试视频理解流水线。 | 返回 Processing Run/Trace 标识；重复调用应遵循幂等和重试规则。 |
| `GET /videos/{video_id}/processing` | 查询处理阶段、百分比、预计剩余时间和错误。 | 前端进度面板轮询此接口。 |
| `GET /videos/{video_id}/timeline` | 获取字幕、画面、OCR、章节、代表帧等多轨时间轴。 | 返回 `TimelineArtifact` 集合。 |
| `GET /videos/{video_id}/semantic-events` | 获取便于 Agent 检索的语义事件。 | 包含时间范围、类型、文本和来源。 |
| `GET /videos/{video_id}/narrative-context` | 获取全片总览、层级章节和快捷理解内容。 | 主界面的“快速了解视频”使用。 |

网页导入示例：

```json
{
  "url": "https://www.bilibili.com/video/BVxxxxxxxxx/",
  "rights_confirmed": true
}
```

推荐调用顺序：

```text
上传或网页导入
  → 取得 video_id
  → POST /processing
  → 轮询 GET /processing
  → 完成后读取 narrative-context、timeline 和 semantic-events
```

## 5. 视频问答

### `POST /videos/{video_id}/questions`

对全片、片段、某一刻或精确帧提问。关键字段：

- `query`：问题，1–2000 字符；
- `target`：问题作用范围；省略时按全片理解；
- `use_web_search`：为 `true` 时必须执行联网研究，并把网页来源与视频证据分开；
- `conversation_id`：继续同一段对话；
- `trace_id`：需要把前端已建立的 Trace 贯穿本次请求时使用。

四种目标：

```json
{"kind": "global"}
```

```json
{
  "kind": "range",
  "time_range": {"start_ms": 120000, "end_ms": 180000}
}
```

```json
{"kind": "moment", "timestamp_ms": 297000, "context_window_ms": 8000}
```

```json
{"kind": "frame", "timestamp_ms": 297000}
```

`moment` 会结合前后文，`frame` 会重新抽取指定时刻的真实画面并优先交给 VLM。响应包含答案、模型使用、视频/图片/网页证据以及 Run/Trace 信息。

## 6. Agent、Trace、成本与系统观测

| 方法与路径 | 用途 |
| --- | --- |
| `GET /agent-runs/{run_id}` | 查看一次处理或问答 Run 的整体状态、预算和各 Agent 步骤。 |
| `GET /agent-runs/{run_id}/trace` | 获取该 Run 的公开 Trace 事件，供运行观测界面增量展示。 |
| `GET /traces/{trace_id}` | 按 Trace ID 查询跨节点事件。 |
| `GET /costs/summary` | 汇总人民币成本，可按模型、Agent、视频和用途理解花费。 |
| `GET /observability/usage` | 获取较细的模型 UsageEvent，定位某次 Token 与费用。 |
| `GET /observability/system` | 获取 Agent 注册表、Harness 策略、模型路由、MCP 和运行组件状态。 |

Trace 是公开执行摘要，不包含隐藏思维链、密钥、完整系统 Prompt 或原始视频内容。

## 7. 垂类 Skill 项目

| 方法与路径 | 用途 | 关键输入 |
| --- | --- | --- |
| `GET /skill-projects` | 获取全部垂类项目。 | 无。 |
| `POST /skill-projects` | 创建“Zc 故事”等长期样本项目。 | `name`、`goal`、可选 `description`。 |
| `GET /skill-projects/{project_id}` | 获取项目、样本流水线、Agent 分配、成本和视频洞察。 | 项目 UUID。 |
| `DELETE /skill-projects/{project_id}` | 删除项目关系。 | 属于破坏性操作；前端必须二次确认。 |
| `POST /skill-projects/{project_id}/videos` | 一次加入 1–50 个网页视频样本并处理。 | `urls`、`rights_confirmed`。 |
| `POST /skill-projects/{project_id}/items/{item_id}/retry` | 重试某个失败样本，不重跑整个项目。 | 项目与样本 ID。 |
| `POST /skill-projects/{project_id}/skill` | 把现有 Skill 关联到项目。 | `skill_id`。 |

项目用于组织同类视频，不等于 Skill。样本处理完成后，用户再选择其中 1–8 条生成独立草案。

## 8. Skill 草案、版本和绑定

| 方法与路径 | 用途 | 关键输入 |
| --- | --- | --- |
| `GET /skills` | 获取全部 Skill 及稳定编号。 | 无。 |
| `POST /skills/generate` | 从已选样本创建一个全新的 Skill v1 草案。 | `video_ids`、`goal`、可选 `display_name`。 |
| `GET /skills/{skill_id}` | 查看内容、全部版本、验证结果和绑定。 | Skill UUID。 |
| `POST /skills/{skill_id}/regenerate` | 用一组新样本为同一个 Skill 生成新版本。 | `video_ids`、可选 `goal`；这是低层版本接口，不等于创建独立 Skill。 |
| `POST /skills/{skill_id}/refine` | 根据自然语言继续修改当前 Skill，生成 v2/v3。 | `instruction`、可选 `base_version`。 |
| `POST /skills/{skill_id}/versions/{version}/publish` | 人工发布指定版本，并生成运行时 Skill 产物。 | Skill UUID 和版本号。 |
| `POST /skills/{skill_id}/rollback` | 将当前发布版本回滚到指定历史版本。 | `version`。 |
| `POST /skills/{skill_id}/bindings` | 把已发布 Skill 绑定到 1–100 个视频。 | `video_ids`。 |
| `DELETE /skills/{skill_id}` | 删除一个 Skill、版本、绑定和项目引用。 | 破坏性操作，必须二次确认。 |
| `POST /skills/batch-delete` | 批量删除 1–100 个 Skill。 | `skill_ids`。 |
| `GET /videos/{video_id}/skill` | 查看视频当前实际绑定的 Skill 与版本。 | 视频 UUID。 |
| `DELETE /videos/{video_id}/skill` | 解绑视频 Skill，恢复通用理解。 | 视频 UUID。 |

最容易混淆的三个动作：

```text
generate   = 新建一个独立 Skill，从 v1 开始
refine     = 按用户意见修改同一个 Skill，形成 v2/v3
regenerate = 给同一个 Skill 换样本重新归纳，形成新版本
```

## 9. v1.1 计划接口：视频脚本生成

以下接口是路线图，当前 OpenAPI 中尚不存在：

| 计划接口 | 目的 |
| --- | --- |
| `POST /script-projects` | 创建脚本项目，保存主题、目标平台、时长、受众和所选 Skill 版本。 |
| `POST /script-projects/{id}/drafts` | 根据创意简述和预设生成脚本 v1。 |
| `POST /script-projects/{id}/drafts/{version}/refine` | 根据自然语言修改，形成 v2/v3。 |
| `POST /script-projects/{id}/drafts/{version}/evaluate` | 做事实、结构、风格、可拍摄性、成本和原创性检查。 |
| `GET /script-projects/{id}/exports/{format}` | 导出 Markdown、JSON、字幕或分镜表。 |

这些接口实现时必须新增 Pydantic Schema、API 集成测试、OpenAPI 快照和本文说明；不得把脚本草案塞进现有 `SkillContent` 字段。

## 10. 常见错误

| 状态/现象 | 常见原因 | 处理 |
| --- | --- | --- |
| `422` | 毫秒传了浮点数、UUID 错误、字段超长 | 对时间戳取整，并查看 Swagger 的 Schema。 |
| `404 Not Found` | 前端仍调用旧路径，或资源 ID 已删除 | 对照本文件与 `openapi.json`，检查浏览器 Network。 |
| `Failed to fetch` | 8000 端口未就绪、代理/CORS、后端异常退出 | 先检查 `/health/live` 与后端错误日志。 |
| 处理接口返回但没结果 | 任务是异步的 | 轮询 `/processing` 并查看对应 Agent Run/Trace。 |
| 勾选联网但没有来源 | MCP/SearXNG 不可用或调用未执行 | 查看 `/observability/system` 的 MCP 状态和 Trace。 |

## 11. 修改接口时的维护清单

1. 修改路由和 Pydantic 请求/响应模型；
2. 增加正常、校验失败、资源不存在和外部依赖失败测试；
3. 重新导出 `docs/api/openapi.json`；
4. 更新本文相应接口的用途和示例；
5. 若为破坏性变更，升级 `/api/vN` 或保留兼容期；
6. 前端类型、错误展示和 Agent Trace 同步更新。
