"""seam-voice 데스크톱 앱 — pywebview 윈도우 + JS↔Python 브리지.

녹음·일괄 처리는 백그라운드 스레드에서 돌고, UI(webui/)는 ``pywebview.api`` 로
:class:`Api` 메서드를 호출한다. ``batch_time`` 자동 처리를 위한 스케줄러 스레드도
앱 수명 동안 함께 돈다.

실행(개발): ``python -m seam_voice.app``
패키징: ``pyinstaller seam-voice.spec`` → ``dist/seam-voice.app``
"""
from __future__ import annotations

import datetime as dt
import shutil
import threading
import time

import webview
import yaml

from .core import processor
from .core.llm import LocalLLM
from .core.logsetup import get_logger
from .core.paths import resource_path
from .core.recorder import Recorder
from .core.settings import Settings

log = get_logger("app")


class Api:
    def __init__(self):
        self.settings = Settings()
        self.settings.ensure_dirs()
        self.llm = LocalLLM(self.settings)
        self._rec: Recorder | None = None
        self._rec_thread: threading.Thread | None = None
        self._batch_thread: threading.Thread | None = None
        self._batch_lock = threading.Lock()    # 배치 중복 시작 방지(#10)
        self._whisper = None                   # Whisper 모델 캐시(#8)
        self._rec_error = ""                   # 마지막 녹음 스트림 오류(#6)
        self._progress: dict = {"phase": "idle", "done": 0, "total": 0}
        self._last_batch_date: dt.date | None = None

    # ---- 상태 ---------------------------------------------------------
    def _recording(self) -> bool:
        return self._rec_thread is not None and self._rec_thread.is_alive()

    def get_status(self) -> dict:
        pu = self.settings.paused_until()
        return {
            "recording": self._recording(),
            "paused": self.settings.is_paused(),
            "within_schedule": self.settings.is_within_schedule(),
            "paused_until": pu.isoformat() if pu else "",
            "llm_status": self.llm.status,
            "llm_error": self.llm.error,
            "rec_error": self._rec_error,
            "batch_running": self._batch_thread is not None and self._batch_thread.is_alive(),
            "progress": self._progress,
            "today": dt.date.today().isoformat(),
        }

    # ---- 녹음 ---------------------------------------------------------
    def start_recording(self) -> dict:
        if self._recording():
            return {"ok": False, "msg": "이미 녹음 중입니다."}
        self._rec_error = ""
        self._rec = Recorder(self.settings, on_error=self._on_rec_error)
        self._rec_thread = threading.Thread(target=self._rec.run, daemon=True)
        self._rec_thread.start()
        return {"ok": True}

    def _on_rec_error(self, msg: str) -> None:
        self._rec_error = msg

    def stop_recording(self) -> dict:
        if self._rec:
            self._rec.stop()
        if self._rec_thread:
            self._rec_thread.join(timeout=3)
        self._rec, self._rec_thread = None, None
        return {"ok": True}

    # ---- 일시정지 -----------------------------------------------------
    def pause(self, minutes: int) -> dict:
        until = self.settings.pause_for(int(minutes))
        return {"ok": True, "until": until.isoformat()}

    def resume(self) -> dict:
        self.settings.resume()
        return {"ok": True}

    # ---- 일괄 처리 ----------------------------------------------------
    def process_now(self, date: str | None = None) -> dict:
        with self._batch_lock:                 # check-then-start 경쟁 방지(#10)
            if self._batch_thread and self._batch_thread.is_alive():
                return {"ok": False, "msg": "이미 처리 중입니다."}
            self._batch_thread = threading.Thread(
                target=self._run_batch, args=(date,), daemon=True
            )
            self._batch_thread.start()
        return {"ok": True}

    def _set_progress(self, done: int, total: int, phase: str) -> None:
        self._progress = {"phase": phase, "done": done, "total": total}

    def _run_batch(self, date: str | None) -> None:
        try:
            if self._whisper is None:          # Whisper 모델 캐시(#8) — 재처리 시 재로드 방지
                self._set_progress(0, 0, "Whisper 모델 로딩")
                self._whisper = processor.load_whisper(self.settings)
            processor.process_day(
                date, self.settings, llm=self.llm,
                model=self._whisper, progress=self._set_progress,
            )
        except Exception as exc:  # 백그라운드 — UI 진행표시로만 보고
            log.exception("일괄 처리 오류: %s", exc)
            self._set_progress(0, 0, f"오류: {exc}")

    # ---- 리포트 -------------------------------------------------------
    def list_reports(self) -> list[str]:
        d = self.settings.reports_dir
        if not d.exists():
            return []
        return sorted((p.stem for p in d.glob("*.md")), reverse=True)

    def get_report(self, date: str) -> str:
        p = self.settings.reports_dir / f"{date}.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    # ---- 설정 ---------------------------------------------------------
    def get_config_text(self) -> str:
        return self.settings.config_path.read_text(encoding="utf-8")

    def save_config_text(self, text: str) -> dict:
        # 먼저 YAML 유효성 검증 — 잘못된 설정을 디스크에 쓰면 다음 실행이 깨짐(#2)
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return {"ok": False, "msg": f"YAML 오류: {exc}"}
        if not isinstance(parsed, dict):
            return {"ok": False, "msg": "설정 최상위는 매핑(key: value)이어야 합니다."}
        try:
            path = self.settings.config_path
            if path.exists():                  # 직전 설정 백업
                shutil.copyfile(path, path.with_name(path.name + ".bak"))
            path.write_text(text, encoding="utf-8")
            self.settings.reload()
            self._whisper = None               # 모델/엔진 설정이 바뀌었을 수 있음 → 캐시 무효화
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ---- LLM 미리 받기 ------------------------------------------------
    def preload_llm(self) -> dict:
        threading.Thread(target=self.llm.preload, daemon=True).start()
        return {"ok": True}

    # ---- 자동 처리 스케줄러 -------------------------------------------
    def _scheduler_loop(self) -> None:
        while True:
            try:
                now = dt.datetime.now()
                hh, mm = str(self.settings.get("processing.batch_time", "18:00")).split(":")
                target = dt.time(int(hh), int(mm))
                running = self._batch_thread is not None and self._batch_thread.is_alive()
                if now.time() >= target and self._last_batch_date != now.date() and not running:
                    self._last_batch_date = now.date()
                    self.process_now(now.date().isoformat())
            except Exception:
                pass
            time.sleep(60)

    def start_scheduler(self) -> None:
        threading.Thread(target=self._scheduler_loop, daemon=True).start()


def main() -> None:
    from .core.logsetup import setup_logging

    setup_logging()
    api = Api()
    api.start_scheduler()
    if api.settings.get("ui.start_recording_on_launch", False):
        api.start_recording()
    window = webview.create_window(
        "seam-voice",
        url=str(resource_path("webui/index.html")),
        js_api=api,
        width=860,
        height=640,
        min_size=(680, 480),
    )
    # 메뉴바 상주(창 닫아도 녹음 유지). 실패해도 창 모드로 계속 동작.
    try:
        from .tray import setup_tray

        setup_tray(api, window, dock_icon=bool(api.settings.get("ui.dock_icon", False)))
    except Exception as exc:  # noqa: BLE001
        log.warning("트레이 초기화 실패(창 모드로 계속): %s", exc)

    webview.start()


if __name__ == "__main__":
    main()
