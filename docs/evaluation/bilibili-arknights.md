# B 站明日方舟人工集成评测

## 目的

这一组视频不是训练集，也不会进入 CI 自动下载。它用于人工触发的端到端验证，覆盖：

| 类别 | 主要难点 |
|---|---|
| 攻略 | 快速游戏操作、高密度 UI、资源和路线变化 |
| 教程 | 高密度口播、PPT/OCR、观点与客观事实混合 |
| Vlog | 手持镜头、多人环境声、场景切换、隐私检查 |

完整清单和问题见 `evals/datasets/bilibili_arknights_v1.yaml`。

## 三层测试策略

1. **CI Smoke**
   只使用项目自制的合成时间轴和合成帧，不访问 B 站。

2. **Metadata Integration**
   由开发者手动运行 yt-dlp 的 metadata-only 模式，检查页面适配器是否仍可解析。

3. **Private End-to-End**
   仅在开发者拥有合法处理权限时下载到 `data/eval/bilibili`，执行 ASR、OCR、
   分段、问答和证据评测。该目录被 Git 忽略。

## 手动运行

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -e ".[media]"
cd ..

# 默认只读取公开元数据
.\backend\.venv\Scripts\python.exe scripts\fetch_eval_media.py `
  --case ak_vlog_ambience_synesthesia_2023

# 只有拥有合法处理权限时才允许下载
.\backend\.venv\Scripts\python.exe scripts\fetch_eval_media.py `
  --case ak_guide_reclamation_skip `
  --download `
  --acknowledge-rights
```

## 版权与隐私

- 多数候选页面标注“未经作者授权，禁止转载”；
- URL 和 BVID 可作为测试定义，原视频、音频和截图不得提交到仓库；
- 不绕过登录、DRM、付费墙、地域限制或站点风控；
- Vlog 可能包含观众、Coser 和现场对话，截图导出前需要人脸与隐私审查；
- 可抓取公开页面不等于自动获得复制和再分发权。

相关规则：

- [哔哩哔哩用户使用协议](https://www.bilibili.com/blackboard/user-rule-linux.html)
- [哔哩哔哩侵权申诉指引](https://www.bilibili.com/html/copyright.html)
