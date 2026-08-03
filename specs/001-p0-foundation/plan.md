# Spec 001 实施计划

## 架构决策

- 采用模块化单体 + API/Worker 多进程入口，P0 不过早拆微服务。
- MySQL 是权威事实库；Qdrant 和 Redis 为可重建派生状态；MinIO 保存媒体证据。
- LangGraph 表达有界状态图，自研 Harness 负责权限、预算、Trace 和停止条件。
- 媒体命令只能经过统一 subprocess 边界，参数列表执行、禁止 Shell、强制超时。
- LiteLLM 作为 Provider 路由边界，业务代码不绑定单一模型 API。

## 交付阶段

1. 领域契约、内存适配器与合成时间轴。
2. Harness、QA Investigator、Evidence Verifier 和 LangGraph QA 图。
3. FastAPI 契约与 Next.js 证据工作台。
4. MySQL 与 Qdrant、S3、Redis、LiteLLM 适配器。
5. FFmpeg/yt-dlp 安全边界和 Temporal probe/audio Workflow。
6. Docker Compose、CI、Eval、Trace、成本和威胁模型文档。
7. 下一阶段：ASR/OCR/镜头/关键帧/VLM/embedding 真实处理闭环。

## 主要风险

| 风险 | 当前控制 |
| --- | --- |
| Agent 循环或费用失控 | 调用前预留预算、重复工具签名限制 |
| Prompt Injection | 视频证据不参与系统权限构造 |
| SSRF | URL 策略 + 下载前 DNS 公网地址检查 |
| 第三方版权 | 默认仅登记，下载需权利确认，CI 只用合成夹具 |
| 基础设施过度复杂 | 内存模式可演示，Docker 模式在装配边界切换 |
