# 数据目录、命名与清理规范

> 生效范围：`data/`、`videos/`、`evals/reports/` 和运行时生成的图片。  
> 当前状态：本规范从 v1.1 新任务开始执行；旧目录暂不批量改名，避免使目录、数据库和截图 URL 之间的引用失效。

## 1. 为什么不能只用 UUID 和毫秒数

UUID 和时间戳适合程序定位，却不方便人查看；只用中文标题又容易重名、超长或包含 Windows 非法字符。因此采用“两层命名”：

- 目录和文件包含可读信息，便于人工维护；
- `manifest.json`、数据库主键和短 ID 保留稳定机器标识，确保重命名或同名视频不会串数据。

## 2. 新任务目录规范

视频刚导入时还不知道章节名称，因此先建立任务目录；完成语义分段后，再生成带大节、小节名称的派生产物。

```text
data/workspaces/
└─ 20260813/
   └─ BV18Awve1Ezk_视频标题_ab12cd34/
      ├─ manifest.json
      ├─ perception/
      │  ├─ asr/transcript_v1.json
      │  ├─ ocr/ocr_v1.json
      │  └─ frames/raw/frame_0001_00-00-01-500.jpg
      ├─ semantic/
      │  ├─ chapters/M01_大节标题/S01_小节标题.json
      │  └─ representatives/
      │     └─ M01_S01_小节标题_K01_00-04-57-000.jpg
      ├─ qa/
      │  └─ 20260813-153012_frame_珊比三技能_a1b2c3d4.json
      └─ exports/
```

字段含义：

| 字段 | 规则 | 示例 |
| --- | --- | --- |
| 日期 | 任务创建日期 `yyyyMMdd` | `20260813` |
| 来源编号 | 优先 BV 号；本地文件使用 `LOCAL` | `BV18Awve1Ezk` |
| 视频名 | 清洗后的原始标题，最长 60 字符 | `访谈完整版` |
| 稳定短 ID | 视频 UUID 前 8 位或内容哈希前 8 位 | `ab12cd34` |
| 大节编号 | `M` + 两位序号 | `M01` |
| 小节编号 | `S` + 两位序号 | `S03` |
| 关键帧编号 | 当前小节内 `K` + 两位序号 | `K02` |
| 时间戳 | `HH-MM-SS-mmm` | `00-04-57-000` |

命名示例：

```text
20260813/BV18Awve1Ezk_视频标题_ab12cd34/
M02_S03_技能机制_K02_00-04-57-000.jpg
```

## 3. 文件名清洗规则

1. Windows 非法字符 `<>:"/\\|?*` 替换为 `_`；
2. 连续空白和下划线折叠为一个 `_`；
3. 去除结尾的点和空格；
4. 标题为空时使用 `untitled`；
5. 可读标题必须附带来源编号或稳定短 ID，禁止只用标题作为唯一键；
6. 查询文本只保留经清洗的短摘要，不把完整私人对话写进文件名；
7. 文件内部必须继续记录完整 `video_id`、`trace_id`、Schema 版本、模型版本和来源路径。

## 4. 媒体库与 Skill 样本

长期保留的视频使用以下结构：

```text
videos/library/
├─ understanding-tasks/
│  └─ 20260813-153012_BV号_视频名/
└─ skill-projects/
   └─ 项目短ID_项目名/
      └─ BV号_视频名/
```

- `understanding-tasks`：用户在主工作台实际理解的视频；
- `skill-projects`：垂类 Skill 的生成、验证或保留集样本；
- 一个物理文件如被多个项目使用，应优先建立引用或内容寻址副本，避免反复下载；
- 已被项目、Skill 版本、评测报告或视频目录引用的媒体不自动清理。

## 5. 默认保留策略

| 数据类别 | 默认保留 | 清理条件 |
| --- | ---: | --- |
| `var/logs/` 服务日志 | 14 天 | 超期即可清理 |
| `data/frames-on-demand/` 临时问答帧 | 7 天 | 超期且没有 `.keep` 标记 |
| `data/processing-cache/` 可重建缓存 | 30 天 | 超期且没有 `.keep` 标记 |
| 孤立的 `data/frames/`、`data/processing/` | 30 天 | 视频不在当前目录中且超期 |
| 孤立的 `data/uploads/`、`data/web-imports/` | 30 天 | 文件未被目录引用且超期 |
| `evals/reports/` 评测报告 | 90 天 | 超期且没有 `.keep` 标记 |
| `data/catalog/`、`data/costs/` | 长期 | 不自动删除 |
| `data/skills/`、`skills/generated/` | 长期 | 只能通过 Skill 删除/退役流程处理 |
| `videos/library/` | 长期 | 只能经媒体库显式清理并检查引用 |

在某个文件或其上级任务目录放置空文件 `.keep`，可以跳过自动清理。成本账本、目录、已发布 Skill 和被引用媒体属于保护数据。

## 6. 安全清理命令

数据清理脚本默认仅预览，不会删除：

```powershell
# 查看将要清理的文件、数量和体积
.\scripts\cleanup-data.ps1

# 人工确认后执行
.\scripts\cleanup-data.ps1 -Apply

# 临时修改保留时间
.\scripts\cleanup-data.ps1 -TransientFrameDays 14 -CacheDays 45
```

日志仍使用独立脚本：

```powershell
.\scripts\cleanup-logs.ps1 -RetentionDays 14 -WhatIf
.\scripts\cleanup-logs.ps1 -RetentionDays 14
```

建议每周日凌晨执行一次 `cleanup-data.ps1 -Apply`。当前不由应用注册开机任务，也不启动常驻 watchdog。确认预览结果符合预期后，可由用户显式注册每周日 03:30 的 Windows 任务计划：

```powershell
# 注册或更新每周任务
.\scripts\register-data-cleanup-task.ps1

# 查询任务
Get-ScheduledTask -TaskName LetsGoVideoAgent-WeeklyDataCleanup

# 不再需要时移除
.\scripts\register-data-cleanup-task.ps1 -Unregister
```

注册脚本不会随 `start-all.cmd` 自动执行，避免后台服务在用户不知情时反复唤起。
每次真正执行清理后会向 `var/logs/maintenance/data-cleanup.jsonl` 追加审计记录；预览模式不写入记录。

## 7. 迁移原则

旧的 UUID 目录和毫秒文件名不能直接批量重命名。v1.1 应先实现统一 `AssetPathPolicy` 和每个任务的 `manifest.json`，让 API 返回逻辑资产 ID，而不是把物理路径当作身份；再提供可回滚迁移命令，逐项更新目录、数据库引用和截图 URL。迁移前必须先生成清单和备份，不得边运行边移动活动任务目录。
