"""从 FastAPI 应用确定性导出 OpenAPI 快照。

运行方式：
    backend/.venv/Scripts/python.exe scripts/export-openapi.py

脚本只构建应用和 Schema，不启动服务、不访问模型 API，也不会产生费用。
"""

from __future__ import annotations

import json
from pathlib import Path

from lets_go_video_agent.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_TARGET = PROJECT_ROOT / "docs" / "api" / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OPENAPI_TARGET.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_TARGET.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI snapshot written: {OPENAPI_TARGET}")


if __name__ == "__main__":
    main()
