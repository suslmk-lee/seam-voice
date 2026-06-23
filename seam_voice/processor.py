"""일괄 처리: 받아쓰기 → 분류 → 요약 → 리포트 → 정리.

흐름:
1. ``raw_audio/<날짜>/*.wav`` 를 faster-whisper로 받아쓰기.
2. 분류: ``keep_keywords`` 우선 매칭 → 없으면 Ollama가 JSON으로 판정
   (``keep / category / participated / reason``). ``discard_non_participated``
   가 켜져 있고 LLM이 "내가 안 낀 대화"로 보면 keep=false. LLM 실패 시 보관.
3. 보관분으로 Ollama 일일 요약.
4. ``reports/<날짜>.md`` 마크다운 리포트 작성.
5. 7일/용량 초과 원본 정리.

사용: ``python -m seam_voice.processor [YYYY-MM-DD]`` (날짜 생략 시 오늘)
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import requests

from .settings import Settings, is_on_ac_power

_CLASSIFY_PROMPT = """당신은 사무실 대화 기록 분류기다. 아래 받아쓰기를 읽고 JSON 객체로만 답하라.
필드:
- keep (bool): 나중에 다시 볼 가치가 있으면 true, 잡담/무의미하면 false
- category (string): "회의" | "업무지시" | "잡담" | "개인" | "기타" 중 하나
- participated (bool): 이 대화에 기기 사용자 본인이 직접 참여한 것으로 보이면 true
- reason (string): 한 문장 근거

받아쓰기:
\"\"\"{text}\"\"\"
"""

_SUMMARY_PROMPT = """다음은 하루치 사무실 대화 받아쓰기 모음이다. 한국어로 간결히 요약하라.
형식:
## 핵심
- (논의/결정사항 불릿)
## 할 일
- (후속 작업이 있으면 불릿, 없으면 "없음")
## 총평
(한 줄)

대화 모음:
{joined}
"""


# ---- LLM (Ollama) -----------------------------------------------------
def _ollama_generate(prompt: str, settings: Settings, *, fmt: str | None = None) -> str:
    base = str(settings.get("llm.base_url", "http://localhost:11434")).rstrip("/")
    payload = {
        "model": settings.get("llm.model", "qwen2.5:7b"),
        "prompt": prompt,
        "stream": False,
    }
    if fmt:
        payload["format"] = fmt
    resp = requests.post(
        f"{base}/api/generate",
        json=payload,
        timeout=int(settings.get("llm.timeout_sec", 120)),
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


# ---- 받아쓰기 ---------------------------------------------------------
def load_whisper(settings: Settings):
    from faster_whisper import WhisperModel

    return WhisperModel(
        settings.get("transcription.model", "large-v3"),
        device=settings.get("transcription.device", "auto"),
        compute_type=settings.get("transcription.compute_type", "int8"),
    )


def transcribe_file(model, wav_path: Path, settings: Settings) -> str:
    segments, _info = model.transcribe(
        str(wav_path),
        language=settings.get("transcription.language", "ko"),
        beam_size=int(settings.get("transcription.beam_size", 5)),
        vad_filter=False,  # 녹음 단계에서 이미 VAD 적용됨
    )
    parts = [seg.text.strip() for seg in segments]
    return " ".join(p for p in parts if p).strip()


def diarize(wav_path: Path, settings: Settings):
    """화자 분리(pyannote) — 미구현 스텁. config에서 기본 off."""
    if not settings.get("diarization.enabled", False):
        return None
    raise NotImplementedError("pyannote 화자 분리는 아직 구현되지 않았습니다.")


# ---- 분류 -------------------------------------------------------------
def classify(text: str, settings: Settings) -> dict:
    for kw in settings.get("retention_rules.keep_keywords", []) or []:
        if kw and kw in text:
            return {
                "keep": True,
                "category": "키워드매칭",
                "participated": True,
                "reason": f"키워드 '{kw}' 포함",
                "by": "keyword",
            }

    try:
        raw = _ollama_generate(_CLASSIFY_PROMPT.format(text=text[:4000]), settings, fmt="json")
        data = json.loads(raw)
        result = {
            "keep": bool(data.get("keep", True)),
            "category": str(data.get("category", "기타")),
            "participated": bool(data.get("participated", True)),
            "reason": str(data.get("reason", "")),
            "by": "llm",
        }
    except Exception as exc:  # LLM/파싱 실패 → 안전하게 보관
        return {
            "keep": True,
            "category": "기타",
            "participated": True,
            "reason": f"LLM 분류 실패로 보관: {exc}",
            "by": "fallback",
        }

    if settings.get("retention_rules.discard_non_participated", True) and not result["participated"]:
        result["keep"] = False
        result["reason"] = result["reason"] or "참여하지 않은 대화"
    return result


# ---- 요약 -------------------------------------------------------------
def summarize_day(joined: str, settings: Settings) -> str:
    return _ollama_generate(_SUMMARY_PROMPT.format(joined=joined[:12000]), settings).strip()


# ---- 리포트 -----------------------------------------------------------
def build_report(date_str: str, kept: list[dict], discarded: list[dict], summary: str) -> str:
    lines = [
        f"# {date_str} 대화 리포트",
        "",
        f"- 보관 {len(kept)}건 / 삭제 {len(discarded)}건",
        "",
        "## 요약",
        summary or "_보관된 대화가 없습니다._",
        "",
        f"## 상세 ({len(kept)}건)",
    ]
    if not kept:
        lines.append("_보관된 대화가 없습니다._")
    for k in kept:
        lines += [
            "",
            f"### {k['file']} — {k.get('category', '기타')}",
            f"> {k.get('reason', '')}  ·  판정: {k.get('by', '')}",
            "",
            k["text"],
        ]
    if discarded:
        lines += ["", f"## 정리됨 ({len(discarded)}건)"]
        lines += [f"- `{d['file']}` — {d.get('reason', '')}" for d in discarded]
    lines.append("")
    return "\n".join(lines)


# ---- 정리(보관 정책) --------------------------------------------------
def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def cleanup(settings: Settings) -> None:
    raw = settings.raw_audio_dir
    if not raw.exists():
        return

    # 1) 보관 일수 초과한 날짜 폴더 삭제
    days = int(settings.get("retention_rules.raw_audio_days", 7))
    cutoff = dt.date.today() - dt.timedelta(days=days)
    for day_dir in sorted(raw.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            day = dt.date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(day_dir, ignore_errors=True)
            print(f"[cleanup] 기간 초과 삭제: {day_dir.name}")

    # 2) 용량 상한 초과 시 오래된 파일부터 삭제
    max_bytes = float(settings.get("retention_rules.max_storage_gb", 20)) * 1024 ** 3
    while _dir_size(raw) > max_bytes:
        wavs = sorted(raw.rglob("*.wav"), key=lambda p: p.stat().st_mtime)
        if not wavs:
            break
        oldest = wavs[0]
        oldest.unlink(missing_ok=True)
        print(f"[cleanup] 용량 초과 삭제: {oldest}")

    # 3) 빈 날짜 폴더 제거
    for day_dir in list(raw.iterdir()):
        if day_dir.is_dir() and not any(day_dir.iterdir()):
            day_dir.rmdir()


# ---- 오케스트레이션 ---------------------------------------------------
def process_day(date_str: str | None = None, settings: Settings | None = None) -> Path | None:
    settings = settings or Settings()
    settings.ensure_dirs()
    date_str = date_str or dt.date.today().isoformat()

    if settings.get("processing.require_ac_power", True) and not is_on_ac_power():
        print("[processor] 전원 미연결 — 일괄 처리 건너뜀.")
        return None

    day_dir = settings.raw_audio_dir / date_str
    wavs = sorted(day_dir.glob("*.wav")) if day_dir.exists() else []
    print(f"[processor] {date_str}: WAV {len(wavs)}개 처리 시작")

    model = None
    kept: list[dict] = []
    discarded: list[dict] = []
    for wav in wavs:
        if model is None:
            model = load_whisper(settings)  # 첫 파일에서만 로드
        text = transcribe_file(model, wav, settings)
        if not text:
            continue
        verdict = classify(text, settings)
        item = {"file": wav.name, "text": text, **verdict}
        if verdict["keep"]:
            kept.append(item)
        else:
            discarded.append(item)
            if settings.get("processing.delete_audio_after_discard", True):
                wav.unlink(missing_ok=True)

    summary = ""
    if kept:
        joined = "\n\n".join(f"[{k['file']}] {k['text']}" for k in kept)
        try:
            summary = summarize_day(joined, settings)
        except Exception as exc:
            summary = f"(요약 실패: {exc})"

    report = build_report(date_str, kept, discarded, summary)
    report_path = settings.reports_dir / f"{date_str}.md"
    report_path.write_text(report, encoding="utf-8")

    cleanup(settings)
    print(f"[processor] 리포트: {report_path} (보관 {len(kept)} / 삭제 {len(discarded)})")
    return report_path


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    process_day(argv[0] if argv else None)


if __name__ == "__main__":
    main()
