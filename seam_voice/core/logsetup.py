"""파일 로깅 — 패키지(.app) 실행 시 stdout 이 사라지므로 로그 파일로 남긴다.

로그: ``~/Library/Logs/seam-voice/seam-voice.log`` (회전 2MB×3).
``setup_logging()`` 은 진입점(app.main / recorder.main / processor.main)에서 1회 호출,
모듈은 ``get_logger(__name 일부)`` 로 로거를 얻는다.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_CONFIGURED = False


def log_dir() -> Path:
    d = Path.home() / "Library" / "Logs" / "seam-voice"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("seam_voice")
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    try:
        fh = logging.handlers.RotatingFileHandler(
            log_dir() / "seam-voice.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass  # 로그 디렉터리 생성 실패해도 앱은 계속

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger("seam_voice." + name)
