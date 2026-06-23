"""시간대 + VAD로 말소리 구간만 WAV로 저장하는 녹음기.

webrtcvad 프레임(기본 30ms) 단위로 발화를 감지한다. 발화 시작 전
``ring_buffer_sec`` 만큼을 ring buffer로 붙여 말 시작 잘림을 막고,
``silence_timeout_sec`` 동안 조용하면 구간을 종료한다. ``min_segment_sec``
미만 구간은 폐기한다. 매 루프에서 스케줄/일시정지를 확인해, 허용 시간대가
아니거나 일시정지면 진행 중 구간을 비우고 대기한다.

앱에서는 ``run()`` 을 백그라운드 스레드로 돌리고 ``stop()`` 으로 종료한다.
저장: ``raw_audio/YYYY-MM-DD/HH-MM-SS_Ns.wav``
"""
from __future__ import annotations

import collections
import datetime as dt
import queue
import signal
import time
import wave

import sounddevice as sd
import webrtcvad

from .logsetup import get_logger
from .settings import Settings

log = get_logger("recorder")


class Recorder:
    def __init__(self, settings: Settings | None = None, on_error=None):
        s = settings or Settings()
        self.settings = s
        self.on_error = on_error      # 스트림 오류 시 콜백(메시지) — UI 알림용

        self.sample_rate = int(s.get("audio.sample_rate", 16000))
        self.channels = int(s.get("audio.channels", 1))
        self.frame_ms = int(s.get("audio.frame_ms", 30))
        self.frame_samples = int(self.sample_rate * self.frame_ms / 1000)
        self.frame_bytes = self.frame_samples * self.channels * 2  # int16

        self.vad = webrtcvad.Vad(int(s.get("audio.vad_aggressiveness", 2)))
        self.silence_timeout = float(s.get("audio.silence_timeout_sec", 1.2))
        self.min_segment = float(s.get("audio.min_segment_sec", 1.0))
        self.max_segment = float(s.get("audio.max_segment_sec", 600))
        self.ring_sec = float(s.get("audio.ring_buffer_sec", 0.3))
        self.ring_frames = max(1, int(self.ring_sec * 1000 / self.frame_ms))

        self._q: "queue.Queue[bytes]" = queue.Queue()
        self._running = False

    # ---- 오디오 콜백 ---------------------------------------------------
    def _callback(self, indata, frames, time_info, status):  # noqa: D401
        if status:
            log.warning("오디오 입력 status: %s", status)  # 입력 오버플로 등
        self._q.put(bytes(indata))

    def _drain_queue(self) -> None:
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    # ---- 저장 ---------------------------------------------------------
    def _flush(self, frames: list[bytes], seg_start: dt.datetime) -> None:
        duration = len(frames) * self.frame_ms / 1000
        if duration < self.min_segment:
            return
        day_dir = self.settings.raw_audio_dir / seg_start.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        name = f"{seg_start.strftime('%H-%M-%S')}_{int(round(duration))}s.wav"
        path = day_dir / name
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(frames))
        log.info("저장: %s (%.1fs)", path, duration)

    # ---- 제어 ---------------------------------------------------------
    def stop(self, *_):
        self._running = False

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self.stop)
            except (ValueError, OSError):
                pass  # 메인 스레드가 아니면(앱 내 스레드 실행) 무시

    # ---- 메인 루프 ----------------------------------------------------
    def run(self) -> None:
        """스트림을 열고 녹음한다. 스트림 오류 시 3초 후 자동 재시작(상주용)."""
        self.settings.ensure_dirs()
        self._install_signal_handlers()
        self._running = True
        log.info("시작 — 스케줄/일시정지에 따라 발화 구간만 저장합니다.")

        while self._running:
            try:
                self._run_stream()
            except Exception as exc:  # 장치 분리·절전/깨어남 등
                log.exception("녹음 스트림 오류 — 3초 후 재시작: %s", exc)
                if self.on_error:
                    try:
                        self.on_error(str(exc))
                    except Exception:
                        pass
                self._drain_queue()
                for _ in range(30):           # stop() 에 반응하며 대기
                    if not self._running:
                        break
                    time.sleep(0.1)
            else:
                break                          # stop() 으로 정상 종료
        log.info("종료.")

    def _run_stream(self) -> None:
        ring: "collections.deque[bytes]" = collections.deque(maxlen=self.ring_frames)
        triggered = False
        voiced: list[bytes] = []
        seg_start: dt.datetime | None = None
        last_voice = 0.0
        gate_ok = True
        last_gate = 0.0

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.frame_samples,
            callback=self._callback,
        ):
            while self._running:
                now = time.monotonic()
                # 게이팅 판정은 ~1초에 한 번만(프레임마다 pause 파일 읽기 방지)
                if now - last_gate >= 1.0:
                    gate_ok = self.settings.is_within_schedule() and not self.settings.is_paused()
                    last_gate = now
                if not gate_ok:
                    if triggered:
                        self._flush(voiced, seg_start)
                        triggered, voiced = False, []
                        ring.clear()
                    self._drain_queue()
                    time.sleep(0.5)
                    continue

                try:
                    frame = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if len(frame) != self.frame_bytes:
                    continue

                is_speech = self.vad.is_speech(frame, self.sample_rate)
                now = time.monotonic()

                if not triggered:
                    ring.append(frame)
                    if is_speech:
                        triggered = True
                        seg_start = dt.datetime.now()
                        voiced = list(ring)      # 프리롤 포함
                        ring.clear()
                        last_voice = now
                else:
                    voiced.append(frame)
                    if is_speech:
                        last_voice = now
                    seg_dur = len(voiced) * self.frame_ms / 1000
                    if (now - last_voice) >= self.silence_timeout or seg_dur >= self.max_segment:
                        self._flush(voiced, seg_start)
                        triggered, voiced = False, []
                        ring.clear()

        if triggered and seg_start is not None:
            self._flush(voiced, seg_start)


def main() -> None:
    from .logsetup import setup_logging

    setup_logging()
    Recorder().run()


if __name__ == "__main__":
    main()
