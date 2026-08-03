"""导出后端 OpenAPI，供前端类型生成和接口漂移检查使用。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lets_go_video_agent.config import Settings
from lets_go_video_agent.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/api/openapi.json"),
    )
    args = parser.parse_args()

    app = create_app(
        settings=Settings(
            repository_backend="memory",
            seed_demo_data=False,
        )
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"{json.dumps(app.openapi(), ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
