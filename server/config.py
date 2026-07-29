from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("FIRE_QDII_DATA_DIR", PROJECT_ROOT / "data"))
DATABASE_PATH = Path(
    os.getenv("FIRE_QDII_DATABASE", DATA_DIR / "fire_qdii.sqlite3")
)
DIST_DIR = PROJECT_ROOT / "dist"
HOST = "127.0.0.1"
PORT = int(os.getenv("FIRE_QDII_PORT", "4310"))
TIMEZONE = "Asia/Shanghai"
