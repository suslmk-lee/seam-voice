"""seam-voice — local, on-device office-conversation recording, transcription, and summary."""
from __future__ import annotations

import subprocess
from pathlib import Path

# Fallback used when git metadata is unavailable (packaged .app, or git not installed).
_FALLBACK_VERSION = "0.1.0"


def _git_version() -> str | None:
    """Return `git describe` for this source checkout, or None if it can't be determined."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


# Single source of truth for the version: the git tag (e.g. "v0.1.0", "v0.1.0-3-gabc1234").
__version__ = _git_version() or _FALLBACK_VERSION
