from __future__ import annotations

import webbrowser
from threading import Timer

import uvicorn

from server.config import DIST_DIR, HOST, PORT


def open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    if not (DIST_DIR / "index.html").exists():
        raise SystemExit("前端尚未构建，请先运行 ./scripts/install_local.sh")
    Timer(1.2, open_browser).start()
    uvicorn.run(
        "server.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        access_log=False,
    )
