# seam-voice

사무실 자리에서 오가는 대화를 **전부 로컬로** 녹음·받아쓰기·요약하는 macOS 메뉴바 앱.
네트워크를 쓰지 않으며(외부 STT/LLM 금지), 받아쓰기는 faster-whisper, 분류·요약은 Ollama 로컬 LLM으로 한다.

## 동작 개요

```
메뉴바 앱 (menubar.py)
 ├─ 녹음 데몬 (recorder.py)  : 허용 시간대 ∧ ¬일시정지일 때 webrtcvad로 발화 구간만 WAV 저장
 └─ 일괄 처리 (processor.py) : faster-whisper 받아쓰기 → Ollama 분류(보관/삭제) → 일일 요약
                               → 날짜별 마크다운 리포트 → 7일/용량 초과 원본 정리
```

데이터(기본 `~/seam-voice-data`, `config.yaml`의 `storage.base_dir`로 변경):

- `raw_audio/YYYY-MM-DD/HH-MM-SS_Ns.wav` — 발화 구간 (7일 후 삭제)
- `reports/YYYY-MM-DD.md` — 받아쓰기 + 요약
- `.state/paused_until.txt` — 일시정지 상태

## 셋업

```bash
cd /workspace/seam-voice
pip install -r requirements.txt          # webrtcvad 컴파일 필요 시: xcode-select --install
brew install ollama && ollama serve
ollama pull qwen2.5:7b
python -m seam_voice.menubar             # 마이크 권한 허용 필요
```

개별 실행:

```bash
python -m seam_voice.recorder            # 녹음 데몬만
python -m seam_voice.processor           # 오늘 일괄 처리
python -m seam_voice.processor 2026-06-23  # 특정 날짜
```

## 설정

모든 옵션은 `seam_voice/config.yaml`에 있다. 주요 항목:

| 키 | 설명 |
|---|---|
| `storage.base_dir` | 데이터 저장 위치 |
| `schedule.{days,windows,lunch}` | 녹음 허용 요일/시간대/점심 제외 |
| `audio.*` | VAD 민감도·프리롤·무음 종료·최소 구간 길이 |
| `transcription.{model,device,compute_type}` | faster-whisper 설정 |
| `llm.{model,base_url}` | Ollama 모델/주소 |
| `retention_rules.{raw_audio_days,max_storage_gb,discard_non_participated,keep_keywords}` | 보관 정책 |
| `processing.{batch_time,require_ac_power}` | 자동 처리 시각/전원 조건 |

## 프라이버시 / 법적 제약 (유지)

- 한국 통신비밀보호법: **본인이 참여한 대화** 녹음은 합법이나 **제3자 대화**는 회색지대 →
  `retention_rules.discard_non_participated`를 기본 ON으로 둔다.
- 녹음 중 메뉴바 마이크 표시는 동료가 인지할 수 있도록 **숨기지 않는다.**
- 전부 로컬·네트워크 미사용 원칙을 유지한다. 외부 API/클라우드 STT·LLM은 도입하지 않는다.

## 상태

프로토타입. 스케줄/일시정지 로직은 검증됨. 실기기(M4)에서 마이크 녹음·받아쓰기·요약 품질은
스모크 테스트 필요. 화자 분리(pyannote)는 미구현 스텁(기본 off). 자세한 배경·백로그는
`docs/HANDOFF.md` 참고.
