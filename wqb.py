#!/usr/bin/env python3
"""CLI entry point:  python agent_tools/wqb.py <command> [options]    (python agent_tools/wqb.py -h)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wqb_tools.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
