"""seam-voice 데스크톱 앱 — pywebview 윈도우 + JS↔Python 브리지.

녹음·일괄 처리는 백그라운드 스레드에서 돌고, UI(webui/)는 ``pywebview.api`` 로
:class:`Api` 메서드를 호출한다. ``batch_time`` 자동 처리를 위한 스케줄러 스레드도
앱 수명 동안 함께 돈다.

실행(개발): ``python -m seam_voice.app``
패키징: ``pyinstaller seam-voice.spec`` → ``dist/seam-voice.app``
"""
from __future__ import annotations

import datetime as dt
import threading
import time

import webview

from .core import processor
from .core.llm import LocalLLM
from .core.paths import resource_path
from .core.recorder import Recorder
from .core.settings import Settings


class Api:
    def __init__(self):
        self.settings = Settings()
        self.settings.ensure_dirs()
        self.llm = LocalLLM(self.settings)
        self._rec: Recorder | None = None
        self._rec_thread: threading.Thread | None = None
        self._batch_thread: threading.Thread | None = None
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
            "batch_running": self._batch_thread is not None and self._batch_thread.is_alive(),
            "progress": self._progress,
            "today": dt.date.today().isoformat(),
        }

    # ---- 녹음 ---------------------------------------------------------
    def start_recording(self) -> dict:
        if self._recording():
            return {"ok": False, "msg": "이미 녹음 중입니다."}
        self._rec = Recorder(self.settings)
        self._rec_thread = threading.Thread(target=self._rec.run, daemon=True)
        self._rec_thread.start()
        return {"ok": True}

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
            processor.process_day(
                date, self.settings, llm=self.llm, progress=self._set_progress
            )
        except Exception as exc:  # 백그라운드 — UI 진행표시로만 보고
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
        try:
            self.settings.config_path.write_text(text, encoding="utf-8")
            self.settings.reload()
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
    api = Api()
    api.start_scheduler()
    webview.create_window(
        "seam-voice",
        url=str(resource_path("webui/index.html")),
        js_api=api,
        width=860,
        height=640,
        min_size=(680, 480),
    )
    webview.start()


if __name__ == "__main__":
    main()
