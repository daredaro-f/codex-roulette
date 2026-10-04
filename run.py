"""Run with `python run.py`. Cross-platform; no shell-specific commands."""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex実験ルーレットを起動する")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true", help="LM Studioへの通信を無効にする")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("ポート番号は1〜65535にしてね。")
    if args.demo:
        os.environ["ROULETTE_DEMO_ONLY"] = "true"
    import uvicorn
    print(f"Codex実験ルーレット：http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run("roulette.app:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
