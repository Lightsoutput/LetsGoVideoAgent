"""Agent 核心。

目录中的角色只承担需要语义判断的工作；媒体下载、转码、ASR、OCR 等确定性步骤位于
`media` 和 `workflows`，不会被包装成“看起来更智能”的 Agent。
"""
