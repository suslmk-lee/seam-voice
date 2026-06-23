"""설정 로드/저장 + 스케줄·일시정지 판단.

- ``config.yaml`` 을 읽어 점(.) 표기로 값을 꺼내고(``get``) 저장한다.
- ``is_within_schedule()`` : 지금이 녹음 허용 요일·시간대(점심 제외)인지.
- ``pause_for()`` / ``is_paused()`` : ``.state/paused_until.txt`` 기반 일시정지.
순수 로직(스케줄/일시정지)은 외부 의존성 없이 단위 테스트 가능하다.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "config.yaml"

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _expand(path: str) -> Path:
    """``~`` 와 환경변수를 펼친 절대경로."""
    return Path(os.path.expanduser(os.path.expandvars(str(path)))).resolve()


def _parse_hhmm(value: str) -> dt.time:
    hh, mm = str(value).split(":")
    return dt.time(int(hh), int(mm))


def _in_window(t: dt.time, start: dt.time, end: dt.time) -> bool:
    """``[start, end)`` 구간 포함 여부(자정 넘는 구간은 다루지 않음)."""
    return start <= t < end


def is_on_ac_power() -> bool:
    """전원(AC) 연결 여부. 확인 불가하면 True(보수적으로 진행)."""
    try:
        out = subprocess.check_output(["pmset", "-g", "batt"], text=True)
    except (OSError, subprocess.SubprocessError):
        return True
    return "AC Power" in out


class Settings:
    def __init__(self, config_path: Path | str = DEFAULT_CONFIG_PATH):
        self.config_path = Path(config_path)
        self.data: dict = {}
        self.reload()

    # ---- 로드/저장 ----------------------------------------------------
    def reload(self) -> None:
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}

    def save(self) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f, allow_unicode=True, sort_keys=False)

    def get(self, dotted_key: str, default=None):
        node = self.data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # ---- 경로 ---------------------------------------------------------
    @property
    def base_dir(self) -> Path:
        return _expand(self.get("storage.base_dir", "~/seam-voice-data"))

    @property
    def raw_audio_dir(self) -> Path:
        return self.base_dir / "raw_audio"

    @property
    def reports_dir(self) -> Path:
        return self.base_dir / "reports"

    @property
    def state_dir(self) -> Path:
        return self.base_dir / ".state"

    def ensure_dirs(self) -> None:
        for d in (self.raw_audio_dir, self.reports_dir, self.state_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- 스케줄 -------------------------------------------------------
    def is_within_schedule(self, now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now()
        sched = self.get("schedule", {}) or {}
        if not sched.get("enabled", True):
            return True

        days = sched.get("days") or ["mon", "tue", "wed", "thu", "fri"]
        allowed = {_WEEKDAYS[d] for d in days if d in _WEEKDAYS}
        if now.weekday() not in allowed:
            return False

        t = now.time()
        windows = sched.get("windows") or [["00:00", "23:59"]]
        if not any(_in_window(t, _parse_hhmm(a), _parse_hhmm(b)) for a, b in windows):
            return False

        for a, b in (sched.get("lunch") or []):
            if _in_window(t, _parse_hhmm(a), _parse_hhmm(b)):
                return False
        return True

    # ---- 일시정지 -----------------------------------------------------
    @property
    def _paused_file(self) -> Path:
        return self.state_dir / "paused_until.txt"

    def pause_for(self, minutes: int, now: dt.datetime | None = None) -> dt.datetime:
        now = now or dt.datetime.now()
        until = now + dt.timedelta(minutes=int(minutes))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._paused_file.write_text(until.isoformat(), encoding="utf-8")
        return until

    def resume(self) -> None:
        try:
            self._paused_file.unlink()
        except FileNotFoundError:
            pass

    def paused_until(self) -> dt.datetime | None:
        if not self._paused_file.exists():
            return None
        try:
            return dt.datetime.fromisoformat(
                self._paused_file.read_text(encoding="utf-8").strip()
            )
        except (ValueError, OSError):
            return None

    def is_paused(self, now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now()
        until = self.paused_until()
        if until is None:
            return False
        if now >= until:          # 만료됐으면 정리하고 해제
            self.resume()
            return False
        return True
