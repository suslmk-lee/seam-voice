# seam-voice — Claude Code 핸드오프 문서

> 사무실 자리에서 오가는 대화를 **전부 로컬로** 녹음·받아쓰기·요약하는 macOS 도구.
> 이 문서 하나로 Claude Code가 이어서 작업할 수 있도록 결정사항·아키텍처·현재 코드·다음 작업을 정리했다.

## 0. 작업 위치 / 첫 단계

- 작업 루트: **`/workspace/seam-voice`**
- Python 패키지명은 하이픈을 못 쓰므로 코드 패키지는 그 안에 **`seam_voice/`** (언더스코어)로 둔다.
- 첫 단계: 아래 "현재 프로토타입 코드" 섹션의 파일들을 `/workspace/seam-voice/seam_voice/` 에 생성하고, `git init` 후 첫 커밋.

목표 트리:
```
/workspace/seam-voice/
├── docs/
│   └── HANDOFF.md       # 이 문서
├── seam_voice/
│   ├── __init__.py
│   ├── config.yaml
│   ├── settings.py      # 설정 로드/저장 + 스케줄·일시정지 판단
│   ├── recorder.py      # 시간대 + VAD로 말소리 구간만 WAV 저장
│   ├── processor.py     # 받아쓰기 → 분류 → 요약 → 리포트 → 정리
│   └── menubar.py       # rumps 메뉴바 앱(전체 제어)
├── requirements.txt
└── README.md
```

## 1. 제품 목표 (사용자 원문 요약)

사무실 자리에 와서 하는 대화(대표님·동료)를 컴퓨터가 켜진 동안 기록하고, 놓치고 싶지 않은 얘기는 보관, 필요 없는 것·무음은 자동 삭제, 하루치 대화를 받아쓰기+요약해 주는 앱.

## 2. 확정된 결정사항 (변경 금지 — 사용자와 합의됨)

| 항목 | 결정 |
|---|---|
| 플랫폼 | macOS 데스크톱 앱 (메뉴바 앱) |
| 대상 기기 | MacBook Air **M4 / 16GB** |
| 처리 위치 | **전부 로컬**, 네트워크 미사용 |
| 받아쓰기 | faster-whisper (기본 `large-v3`, 대안 `large-v3-turbo` / whisper.cpp Metal) |
| LLM | **Ollama 로컬** (`qwen2.5:7b`, 한국어) — 분류·요약용 |
| 화자 구분 | **익명 화자1/2만** (이름 자동 매칭은 범위 밖, 추후 옵션) |
| 녹음 범위 | 컴퓨터 켜진 동안 + **허용 시간대 설정**(예: 평일 09:00–17:00, 점심 제외) |
| 무음 처리 | VAD로 말소리 구간만 저장(무음은 파일로 안 남김) |
| 원본 보관 | **7일** 후 자동 삭제 (+ 용량 상한 초과 시 오래된 것부터) |
| 설정 | 모든 옵션을 메뉴/`config.yaml`에서 조정 |
| 배터리 | 받아쓰기·요약은 전원 연결 시에만(옵션) |

## 3. 아키텍처

```
메뉴바 앱 (menubar.py)
   ├─ 녹음 데몬 (recorder.py)  : 허용 시간대 ∧ ¬일시정지일 때만, webrtcvad로 발화 구간만 WAV 저장
   └─ 일괄 처리 (processor.py) : faster-whisper 받아쓰기 → Ollama 분류(보관/삭제) → Ollama 일일 요약
                                 → 날짜별 마크다운 리포트 → 7일/용량 초과 원본 정리
```

데이터 저장(기본 `~/seam-voice-data`, config의 `storage.base_dir`로 변경):
- `raw_audio/YYYY-MM-DD/HH-MM-SS_Ns.wav` — 발화 구간 (7일 후 삭제)
- `reports/YYYY-MM-DD.md` — 받아쓰기 + 요약
- `.state/paused_until.txt` — 일시정지 상태

핵심 흐름 디테일:
- **recorder**: webrtcvad 프레임(30ms) 단위로 발화 감지. 발화 시작 전 0.3초를 ring buffer로 붙여 말 시작 잘림 방지. `silence_timeout_sec` 만큼 조용하면 구간 종료, `min_segment_sec` 미만은 폐기. 매 루프에서 `settings.is_within_schedule()` / `is_paused()` 확인.
- **processor**: 분류는 `keep_keywords` 우선 매칭 → 없으면 Ollama가 JSON(`keep/category/participated/reason`)으로 판정. `discard_non_participated`가 켜져 있고 LLM이 "내가 안 낀 대화"로 보면 keep=false. LLM 실패 시 안전하게 보관.
- **menubar**: rumps. 녹음 시작/정지(서브프로세스로 recorder 실행), 일시정지(15/30/60분), 지금 일괄 처리, 오늘 리포트 열기, 설정 열기/다시 읽기. 타이머로 상태 아이콘 갱신(🔴/🎙️/⏸️/⚪️) + `batch_time`에 하루 1회 자동 처리.

## 4. 현재 상태

- 프로토타입 **작성 완료, 문법 검사 통과**. 스케줄(요일/시간/점심) + 일시정지 로직은 단위 테스트로 동작 확인됨.
- **실기기에서 미검증**: 실제 마이크 녹음, faster-whisper 받아쓰기 품질, Ollama 분류/요약 품질, rumps 메뉴바 UI는 맥에서 직접 돌려봐야 함.
- 화자 분리(pyannote)는 **미구현(스텁)** — config에서 기본 off.

## 5. 다음 작업 백로그 (우선순위 순)

1. **실기기 스모크 테스트**: M4에서 `recorder` 5분 녹음 → `processor`로 받아쓰기/요약/리포트까지 end-to-end 확인. Whisper 모델별 속도(대형 vs turbo) 측정 후 기본값 조정.
2. **whisper.cpp(Metal) 백엔드 추가**: `transcription.engine: whisper.cpp` 경로 구현. M-시리즈에서 faster-whisper(CPU)보다 빠름.
3. **화자 분리 구현**: pyannote.audio + HF 토큰 연동, 익명 화자1/2 라벨을 리포트에 표기. 리포트에서 수동 라벨 보정 가능하게.
4. **로그인 시 자동 실행**: `launchd` plist 또는 `py2app`로 `.app` 패키징 후 로그인 항목 등록.
5. **리포트 뷰어**: 날짜별 리포트를 검색·열람하는 간단한 로컬 UI(메뉴 또는 작은 웹뷰).
6. **견고성**: recorder 크래시 자동 재시작, 디스크 용량 모니터링/알림, 원본 오디오 암호화 저장 옵션.
7. **테스트**: settings 스케줄 로직 pytest화, processor를 가짜 LLM/Whisper로 모킹해 파이프라인 테스트.

## 6. 셋업 (README와 동일)

```bash
cd /workspace/seam-voice
pip install -r requirements.txt          # webrtcvad 컴파일 필요 시: xcode-select --install
brew install ollama && ollama serve
ollama pull qwen2.5:7b
python -m seam_voice.menubar             # 마이크 권한 허용 필요
```
개별 실행: `python -m seam_voice.recorder` / `python -m seam_voice.processor [YYYY-MM-DD]`

## 7. 법적 / 프라이버시 제약 (반드시 유지)

- 한국 통신비밀보호법: **본인이 참여한 대화** 녹음은 합법이나, **참여하지 않은 제3자 대화**는 회색지대 → `retention_rules.discard_non_participated` 기본 ON 유지.
- 녹음 중 메뉴바 마이크 표시가 노출됨(동료가 인지 가능) — 숨기지 말 것.
- 전부 로컬·네트워크 미사용 원칙 유지. 외부 API/클라우드 STT/LLM 도입 금지(사용자 결정).

---

## 8. 현재 프로토타입 코드 (그대로 생성)

> 패키지 디렉터리는 `seam_voice/`. 아래 내용을 파일별로 생성하면 된다.
> (`config.yaml`의 `base_dir`는 `~/seam-voice-data` 권장으로 바꿔둠 — 원하면 조정)

### `seam_voice/__init__.py`
```python
"""seam-voice — 로컬 사무실 대화 녹음·받아쓰기·요약."""
__version__ = "0.1.0"
```

### `requirements.txt`
```
sounddevice>=0.4.6
webrtcvad>=2.0.10
numpy>=1.24
faster-whisper>=1.0.0
requests>=2.31
PyYAML>=6.0
rumps>=0.4.0
# 선택(화자분리): pyannote.audio>=3.1  (Hugging Face 토큰 필요)
```

> 나머지 모듈(`config.yaml`, `settings.py`, `recorder.py`, `processor.py`, `menubar.py`)의
> 전체 소스는 함께 전달된 프로토타입 파일을 그대로 복사한다. 각 파일은 독립적으로 동작하며,
> import 경로의 패키지명만 `deskscribe` → `seam_voice`로 바꾸면 된다(아래 9절 참고).

## 9. 마이그레이션 메모 (프로토타입 → seam-voice)

전달된 프로토타입은 패키지명이 `deskscribe`다. seam-voice로 옮길 때:
1. 폴더 `deskscribe/` → `seam_voice/` 로 이름 변경.
2. `menubar.py` 내부의 서브프로세스 호출 `["python", "-m", "deskscribe.recorder"]` → `["python", "-m", "seam_voice.recorder"]`.
3. 상대 import(`from .settings import ...`, `from . import processor`)는 그대로 동작하므로 수정 불필요.
4. `config.yaml`의 `storage.base_dir`를 `~/seam-voice-data`로 변경(선택).
5. 문법 검사: `python -m py_compile seam_voice/*.py`.
