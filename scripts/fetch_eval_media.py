"""手动获取公开评测页面的元数据，或在有权处理时下载到本地忽略目录。

默认只读取元数据。脚本不会处理登录、Cookie、DRM 或付费墙，也不会把媒体写入 Git。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evals" / "datasets" / "bilibili_arknights_v1.yaml"
DEFAULT_OUTPUT = ROOT / "data" / "eval" / "bilibili"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case", required=True, help="数据集中的 case id")
    parser.add_argument(
        "--download",
        action="store_true",
        help="下载媒体；省略时只读取公开元数据",
    )
    parser.add_argument(
        "--acknowledge-rights",
        action="store_true",
        help="明确确认自己拥有处理该视频的权限",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_case(dataset_path: Path, case_id: str) -> dict[str, Any]:
    payload = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    for case in payload["cases"]:
        if case["id"] == case_id:
            return case
    raise SystemExit(f"未找到评测用例: {case_id}")


def build_command(case: dict[str, Any], *, download: bool, output: Path) -> list[str]:
    source = case["source"]
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--socket-timeout",
        "15",
        "--retries",
        "1",
        "--no-warnings",
    ]
    if download:
        command.extend(
            [
                "--format",
                "bv*[height<=720]+ba/b[height<=720]",
                "--merge-output-format",
                "mp4",
                "--output",
                str(output / f"{case['id']}.%(ext)s"),
            ]
        )
    else:
        command.extend(["--skip-download", "--dump-single-json"])
    command.append(source["url"])
    return command


def main() -> int:
    args = parse_args()
    case = load_case(args.dataset.resolve(), args.case)
    if args.download and not args.acknowledge_rights:
        raise SystemExit("下载前必须同时传入 --acknowledge-rights")
    if case["rights"]["usage"] == "metadata_only_until_rights_verified" and args.download:
        raise SystemExit("该用例尚未核实处理权限，目前只允许读取元数据")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = build_command(case, download=args.download, output=output)
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
    except ModuleNotFoundError as exc:
        raise SystemExit('请先安装后端 media extra：pip install -e ".[media]"') from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemExit("yt-dlp 在 90 秒内未完成，已主动终止") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"yt-dlp 失败：{exc.stderr[-500:]}") from exc

    if not args.download:
        metadata = json.loads(result.stdout)
        selected = {
            "id": metadata.get("id"),
            "title": metadata.get("title"),
            "uploader": metadata.get("uploader"),
            "duration": metadata.get("duration"),
            "webpage_url": metadata.get("webpage_url"),
            "extractor": metadata.get("extractor"),
        }
        target = output / f"{case['id']}.metadata.json"
        target.write_text(
            json.dumps(selected, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(target)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

