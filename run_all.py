"""Launch all TalentIQ services — each in its own terminal window.

Usage:
    uv run python run_all.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(ROOT, "talent_ui")

UV = "uv"

SERVICES = [
    {
        "name": "MCP-Server",
        "cmd": f'cd /d "{ROOT}" && {UV} run --package talent_backend python -m talent_backend.mcp_server',
    },
    {
        "name": "Backend-API",
        "cmd": f'cd /d "{ROOT}" && {UV} run --package talent_backend python -m talent_backend',
    },
    {
        "name": "Frontend-UI",
        "cmd": f'cd /d "{UI_DIR}" && npm run dev',
    },
]

if __name__ == "__main__":
    print("\033[36m" + "=" * 50)
    print("  TalentIQ — Launching services in separate terminals")
    print("=" * 50 + "\033[0m\n")

    for svc in SERVICES:
        print(f"\033[32m▶ {svc['name']}\033[0m")
        if sys.platform == "win32":
            subprocess.Popen(
                f'start "{svc["name"]}" cmd /k "{svc["cmd"]}"',
                shell=True,
            )
        else:
            # macOS / Linux — use the default terminal
            subprocess.Popen(["bash", "-c", svc["cmd"]])

    print(f"\n\033[36m{'=' * 50}")
    print("  Three terminal windows launched:")
    print("    MCP Server  → http://localhost:3002/mcp")
    print("    Backend API → http://localhost:8000")
    print("    Frontend UI → http://localhost:5173")
    print(f"{'=' * 50}\033[0m")
    print("  Close each terminal window to stop its service.\n")
