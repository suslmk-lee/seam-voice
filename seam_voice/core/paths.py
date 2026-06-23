"""경로 helper — 개발 실행과 PyInstaller 동결(.app) 실행을 모두 대응.

- ``resource_path``  : 번들에 동봉된 읽기전용 리소스(webui, 기본 config).
- ``app_support_dir``: 사용자별 쓰기 가능 디렉터리(설정/모델 캐시).
- ``user_config_path``: 쓰기 가능한 config.yaml. 없으면 번들 기본값을 복사해 seed.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "seam-voice"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(rel: str) -> Path:
    """동봉 리소스 절대경로. 동결 시 ``sys._MEIPASS``, 개발 시 ``seam_voice/`` 기준."""
    if is_frozen():
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent  # .../seam_voice
    return base / rel


def app_support_dir() -> Path:
    base = Path.home() / "Library" / "Application Support" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def user_config_path() -> Path:
    override = os.environ.get("SEAM_VOICE_CONFIG")
    if override:
        return Path(override)
    cfg = app_support_dir() / "config.yaml"
    if not cfg.exists():
        default = resource_path("core/config.yaml")
        if default.exists():
            shutil.copyfile(default, cfg)
    return cfg
