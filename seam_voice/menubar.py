"""rumps 메뉴바 앱 — 전체 제어.

메뉴: 녹음 시작/정지(서브프로세스로 recorder 실행), 일시정지(15/30/60분),
지금 일괄 처리, 오늘 리포트 열기, 설정 열기/다시 읽기.
타이머(5초)로 상태 아이콘을 갱신(🔴/🎙️/⏸️/⚪️)하고, ``batch_time`` 에
하루 1회 자동 일괄 처리를 돌린다.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
import threading
from pathlib import Path

import rumps

from . import processor
from .settings import Settings


class SeamVoiceApp(rumps.App):
    def __init__(self):
        super().__init__("seam-voice", title="⚪️", quit_button="종료")
        self.settings = Settings()
        self.settings.ensure_dirs()
        self._rec_proc: subprocess.Popen | None = None
        self._last_batch_date: dt.date | None = None
        self._batch_running = False

        self.menu = [
            rumps.MenuItem("녹음 시작", callback=self.start_recording),
            rumps.MenuItem("녹음 정지", callback=self.stop_recording),
            None,
            (
                "일시정지",
                [
                    rumps.MenuItem("15분", callback=lambda _: self.pause(15)),
                    rumps.MenuItem("30분", callback=lambda _: self.pause(30)),
                    rumps.MenuItem("60분", callback=lambda _: self.pause(60)),
                    rumps.MenuItem("해제", callback=lambda _: self.resume()),
                ],
            ),
            None,
            rumps.MenuItem("지금 일괄 처리", callback=self.process_now),
            rumps.MenuItem("오늘 리포트 열기", callback=self.open_report),
            None,
            rumps.MenuItem("설정 열기", callback=self.open_settings),
            rumps.MenuItem("설정 다시 읽기", callback=self.reload_settings),
        ]

        self.timer = rumps.Timer(self.tick, 5)
        self.timer.start()

    # ---- 녹음 ---------------------------------------------------------
    def _recording(self) -> bool:
        return self._rec_proc is not None and self._rec_proc.poll() is None

    def start_recording(self, _=None):
        if self._recording():
            rumps.notification("seam-voice", "", "이미 녹음 중입니다.")
            return
        self._rec_proc = subprocess.Popen([sys.executable, "-m", "seam_voice.recorder"])
        rumps.notification("seam-voice", "", "녹음을 시작했습니다.")

    def stop_recording(self, _=None):
        if self._recording():
            self._rec_proc.terminate()
            try:
                self._rec_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._rec_proc.kill()
        self._rec_proc = None
        rumps.notification("seam-voice", "", "녹음을 정지했습니다.")

    # ---- 일시정지 -----------------------------------------------------
    def pause(self, minutes: int):
        until = self.settings.pause_for(minutes)
        rumps.notification("seam-voice", "", f"{minutes}분 일시정지 ({until:%H:%M}까지)")

    def resume(self):
        self.settings.resume()
        rumps.notification("seam-voice", "", "일시정지를 해제했습니다.")

    # ---- 일괄 처리 ----------------------------------------------------
    def process_now(self, _=None):
        if self._batch_running:
            rumps.notification("seam-voice", "", "이미 일괄 처리 중입니다.")
            return
        rumps.notification("seam-voice", "", "일괄 처리를 시작합니다…")
        threading.Thread(target=self._run_batch, args=(None,), daemon=True).start()

    def _run_batch(self, date_str: str | None):
        self._batch_running = True
        try:
            path = processor.process_day(date_str, self.settings)
            if path:
                rumps.notification("seam-voice", "완료", f"리포트: {Path(path).name}")
        except Exception as exc:  # 백그라운드 스레드 — 알림으로만 보고
            rumps.notification("seam-voice", "오류", str(exc))
        finally:
            self._batch_running = False

    # ---- 리포트/설정 --------------------------------------------------
    def open_report(self, _=None):
        path = self.settings.reports_dir / f"{dt.date.today().isoformat()}.md"
        if path.exists():
            subprocess.run(["open", str(path)])
        else:
            rumps.notification("seam-voice", "", "오늘 리포트가 아직 없습니다.")

    def open_settings(self, _=None):
        subprocess.run(["open", str(self.settings.config_path)])

    def reload_settings(self, _=None):
        self.settings.reload()
        rumps.notification("seam-voice", "", "설정을 다시 읽었습니다.")

    # ---- 타이머: 상태 아이콘 + 자동 처리 -------------------------------
    def tick(self, _=None):
        if self.settings.is_paused():
            self.title = "⏸️"
        elif self._recording() and self.settings.is_within_schedule():
            self.title = "🎙️"   # 허용 시간대 + 녹음 중 (실제 캡처)
        elif self._recording():
            self.title = "🔴"    # 녹음 데몬은 떠 있으나 시간대 밖 대기
        else:
            self.title = "⚪️"   # 정지
        self._maybe_auto_batch()

    def _maybe_auto_batch(self):
        if self._batch_running:
            return
        now = dt.datetime.now()
        try:
            hh, mm = str(self.settings.get("processing.batch_time", "18:00")).split(":")
            target = dt.time(int(hh), int(mm))
        except (ValueError, AttributeError):
            return
        if now.time() >= target and self._last_batch_date != now.date():
            self._last_batch_date = now.date()
            threading.Thread(
                target=self._run_batch, args=(now.date().isoformat(),), daemon=True
            ).start()


def main() -> None:
    SeamVoiceApp().run()


if __name__ == "__main__":
    main()
