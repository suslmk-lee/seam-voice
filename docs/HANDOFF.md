# seam-voice — Claude Code 핸드오프 문서

> 사무실 자리에서 오가는 대화를 **전부 로컬로** 녹음·받아쓰기·요약하는 macOS 도구.
> 이 문서 하나로 Claude Code가 이어서 작업할 수 있도록 결정사항·아키텍처·현재 코드·다음 작업을 정리했다.

> **업데이트 2026-06-23 — 아키텍처 변경(사용자 승인):**
> UI/패키징을 **rumps 메뉴바 → pywebview 웹UI + PyInstaller 단일 `.app`** 로,
> LLM을 **Ollama → llama-cpp-python(인프로세스 GGUF)** 로 변경했다. 코어 모듈은
> `seam_voice/core/` 로 이동했고 모든 코드를 실제로 생성·검증했다(8·9절은 구버전 기록).
> 최신 사양은 아래 0~6절과 `README.md` 기준.

## 0. 작업 위치 / 첫 단계

- 작업 루트: **`/workspace/seam-voice`**
- Python 패키지명은 하이픈을 못 쓰므로 코드 패키지는 그 안에 **`seam_voice/`** (언더스코어)로 둔다.
- 첫 단계: 아래 "현재 프로토타입 코드" 섹션의 파일들을 `/workspace/seam-voice/seam_voice/` 에 생성하고, `git init` 후 첫 커밋.

현재 트리(생성·검증 완료):
```
/Users/minkyu/workspace/seam-voice/
├── docs/HANDOFF.md
├── main.py               # 실행/패키징 launcher(절대 import → 상대 import 보장)
├── seam_voice/
│   ├── __init__.py
│   ├── app.py            # pywebview 윈도우 + JS↔Python 브리지 + 자동처리 스케줄러
│   ├── core/
│   │   ├── paths.py      # 번들/사용자 경로(개발·동결 모두 대응)
│   │   ├── settings.py   # 설정 로드/저장 + 스케줄·일시정지·AC전원
│   │   ├── recorder.py   # VAD로 발화 구간만 WAV 저장(백그라운드 스레드)
│   │   ├── llm.py        # llama-cpp-python 래퍼(첫 실행 시 GGUF 다운로드)
│   │   ├── processor.py  # 받아쓰기 → 분류 → 요약 → 리포트 → 정리
│   │   └── config.yaml   # 기본 설정(앱 첫 실행 시 사용자 위치로 복사)
│   ├── tray.py           # macOS 메뉴바(NSStatusItem) 상주 — 창 닫아도 녹음 유지
│   └── webui/            # index.html / style.css / app.js
├── seam-voice.spec       # PyInstaller 단일 .app 스펙
├── requirements.txt
└── README.md
```

## 1. 제품 목표 (사용자 원문 요약)

사무실 자리에 와서 하는 대화(대표님·동료)를 컴퓨터가 켜진 동안 기록하고, 놓치고 싶지 않은 얘기는 보관, 필요 없는 것·무음은 자동 삭제, 하루치 대화를 받아쓰기+요약해 주는 앱.

## 2. 확정된 결정사항 (변경 금지 — 사용자와 합의됨)

| 항목 | 결정 |
|---|---|
| 플랫폼 | macOS 데스크톱 앱 — **pywebview 웹UI + PyInstaller 단일 `.app`** (구: rumps 메뉴바) |
| 대상 기기 | MacBook Air **M4 / 16GB** |
| 처리 위치 | **전부 로컬**, 네트워크 미사용(모델 최초 다운로드 제외) |
| 받아쓰기 | faster-whisper (기본 `large-v3`, 대안 `large-v3-turbo` / whisper.cpp Metal) |
| LLM | **llama-cpp-python 인프로세스 GGUF** (`Qwen2.5-7B-Instruct` Q4_K_M, 한국어) — 분류·요약용. Ollama 불필요 |
| 화자 구분 | **익명 화자1/2만** (이름 자동 매칭은 범위 밖, 추후 옵션) |
| 녹음 범위 | 컴퓨터 켜진 동안 + **허용 시간대 설정**(예: 평일 09:00–17:00, 점심 제외) |
| 무음 처리 | VAD로 말소리 구간만 저장(무음은 파일로 안 남김) |
| 원본 보관 | **7일** 후 자동 삭제 (+ 용량 상한 초과 시 오래된 것부터) |
| 설정 | 모든 옵션을 메뉴/`config.yaml`에서 조정 |
| 배터리 | 받아쓰기·요약은 전원 연결 시에만(옵션) |

## 3. 아키텍처

```
데스크톱 앱 (app.py, pywebview)
   ├─ webui/                    : HTML/JS UI ↔ Api 브리지(녹음/일시정지/처리/리포트/설정)
   ├─ 녹음 (core/recorder.py)   : 백그라운드 스레드. 허용 시간대 ∧ ¬일시정지일 때 webrtcvad로 발화 구간만 WAV
   ├─ 일괄 처리 (core/processor): faster-whisper 받아쓰기 → 분류(보관/삭제) → 일일 요약
   │                              → 날짜별 마크다운 리포트 → 7일/용량 초과 원본 정리
   └─ LLM (core/llm.py)         : llama-cpp-python 인프로세스 GGUF(분류·요약). 첫 사용 시 모델 다운로드
```

녹음·처리는 별도 데몬/서브프로세스가 아니라 **앱 프로세스 내 백그라운드 스레드**다
(PyInstaller 동결 시 `python -m` 재실행이 불가하므로). `batch_time` 자동 처리는
`app.py` 의 스케줄러 스레드가 담당.

데이터 저장(기본 `~/seam-voice-data`, config의 `storage.base_dir`로 변경):
- `raw_audio/YYYY-MM-DD/HH-MM-SS_Ns.wav` — 발화 구간 (7일 후 삭제)
- `reports/YYYY-MM-DD.md` — 받아쓰기 + 요약
- `.state/paused_until.txt` — 일시정지 상태

핵심 흐름 디테일:
- **recorder**: webrtcvad 프레임(30ms) 단위로 발화 감지. 발화 시작 전 0.3초를 ring buffer로 붙여 말 시작 잘림 방지. `silence_timeout_sec` 만큼 조용하면 구간 종료, `min_segment_sec` 미만은 폐기. 매 루프에서 `settings.is_within_schedule()` / `is_paused()` 확인.
- **processor**: 분류는 `keep_keywords` 우선 매칭 → 없으면 로컬 LLM이 JSON(`keep/category/participated/reason`)으로 판정. `discard_non_participated`가 켜져 있고 LLM이 "내가 안 낀 대화"로 보면 keep=false. LLM 실패 시 안전하게 보관. UI 진행률을 위해 `progress(done,total,phase)` 콜백 지원.
- **llm**: `LocalLLM` 이 `llama_cpp.Llama.from_pretrained` 로 GGUF를 lazy 로드(첫 사용 시 `~/Library/Application Support/seam-voice/models` 로 다운로드). Apple Silicon은 `n_gpu_layers:-1` Metal 오프로드. `as_json=True` 시 `response_format={"type":"json_object"}`.
- **app/webui**: pywebview 윈도우. Api 메서드를 `pywebview.api.*` 로 호출 — 녹음 시작/정지(스레드), 일시정지(15/30/60), 지금 처리, 리포트 목록/열람(웹뷰 내 마크다운 렌더), config.yaml 편집·저장. 1.5초 폴링으로 상태칩(녹음중/대기/일시정지/정지)·진행률 갱신. `batch_time` 자동 처리는 스케줄러 스레드.
- **paths/settings**: 설정은 사용자 쓰기 위치(`~/Library/Application Support/seam-voice/config.yaml`)에서 로드하며 없으면 번들 기본값을 복사. 동결 실행은 `resource_path` 가 `sys._MEIPASS` 기준으로 webui/기본config 를 찾는다.

## 4. 현재 상태 (M4에서 검증, 2026-06-23)

검증 완료:
- 의존성 설치(llama-cpp-python Metal arm64 빌드, pywebview 6.2.1, faster-whisper 1.2.1, ctranslate2, pyobjc-WebKit), 전체 import.
- 마이크 캡처(실오디오 수신 확인), VAD 녹음 루프 정상 개폐.
- **받아쓰기**: faster-whisper `large-v3` 가 한국어 문장을 정확히 받아씀(`say` 합성 음성으로 검증).
- **LLM**: llama-cpp-python + `Qwen2.5-7B` 가 분류(JSON 강제 파싱)·일일 요약을 정확히 수행. 키워드 우선 매칭 경로도 동작.
- **파이프라인 end-to-end**: WAV 3건 → 받아쓰기 → 보관2/삭제1 → 요약 → 리포트 정상.
- **PyInstaller `.app`**: 빌드(248MB) + 번들 실행파일 기동 성공. webui·config·libllama·libggml-metal·_webrtcvad·libportaudio 동봉 확인.
- **메뉴바 상주(tray.py)**: NSStatusItem 생성, 창 닫기→숨김(상주)·종료 메뉴→실제 종료 로직을 pywebview Event 로 결정적 검증. 트레이 포함 번들 기동 OK.
- 스케줄/일시정지/리포트 빌드 단위 로직.

빌드 시 주의(겪은 이슈, 해결됨):
- `setuptools>=81` 은 `pkg_resources` 제거 → webrtcvad import 깨짐. `requirements.txt` 에 `setuptools<81` 고정.
- PyInstaller entry 를 `seam_voice/app.py` 로 두면 `__main__` 실행 시 상대 import 실패 → `main.py` launcher 를 entry 로.
- sounddevice(portaudio)·webrtcvad(C확장)는 spec 에서 `collect_all` 로 명시 수집해야 동봉됨.

미검증/남음:
- pywebview **GUI 창/메뉴바 메뉴의 실제 클릭 동작**은 개발 실행으로 띄워 클릭 검증 권장(코드 경로·상주 로직은 검증됨).
- 화자 분리(pyannote)는 **미구현(스텁)** — config 기본 off.
- **로그인 시 자동 실행**: 아직 미구현(launchd LaunchAgent 또는 로그인 항목 등록). 상주 자체는 tray 로 해결됨.

## 5. 다음 작업 백로그 (우선순위 순)

1. **실기기 스모크 테스트 + 빌드**: M4에서 `pip install -r requirements.txt` → `python -m seam_voice.app` 로 녹음→처리→리포트 end-to-end 확인. 이어서 `pyinstaller seam-voice.spec` 로 `.app` 빌드(네이티브 패키지가 많아 spec 조정 가능성: llama_cpp의 `*.metal`/`libllama`, ctranslate2, portaudio, pyobjc WebKit 동봉 확인).
2. ~~트레이 상주~~ **(완료)**: `tray.py` 의 NSStatusItem 으로 창 닫아도 녹음 유지. 남은 건 **로그인 시 자동 실행**(launchd LaunchAgent plist 또는 시스템설정 로그인 항목 등록)뿐.
3. **whisper.cpp(Metal) 백엔드 추가**: `transcription.engine: whisper.cpp` 경로 구현. M-시리즈에서 faster-whisper(CPU)보다 빠름.
4. **화자 분리 구현**: pyannote.audio + HF 토큰 연동, 익명 화자1/2 라벨을 리포트에 표기. 리포트에서 수동 라벨 보정.
5. **UI 개선**: 리포트 내 검색, 설정을 폼으로(yaml 직접편집 대체), 모델 다운로드 진행률 표시.
6. **견고성**: 녹음 스레드 크래시 자동 재시작, 디스크 용량 모니터링/알림, 원본 오디오 암호화 저장 옵션.
7. **테스트**: settings 스케줄 로직 pytest화, processor를 가짜 LLM/Whisper로 모킹해 파이프라인 테스트.

## 6. 셋업 (README와 동일)

```bash
cd /Users/minkyu/workspace/seam-voice
pip install -r requirements.txt          # webrtcvad 컴파일 필요 시: xcode-select --install
python -m seam_voice.app                 # 앱 창 실행 (첫 녹음 시 마이크 권한 허용)
```
개별 실행(디버깅): `python -m seam_voice.core.recorder` / `python -m seam_voice.core.processor [YYYY-MM-DD]`

단일 .app 빌드: `pip install pyinstaller && pyinstaller seam-voice.spec` → `dist/seam-voice.app`
(Ollama 설치/실행은 더 이상 필요 없음 — LLM은 인프로세스 GGUF로 첫 실행 시 자동 다운로드)

## 7. 법적 / 프라이버시 제약 (반드시 유지)

- 한국 통신비밀보호법: **본인이 참여한 대화** 녹음은 합법이나, **참여하지 않은 제3자 대화**는 회색지대 → `retention_rules.discard_non_participated` 기본 ON 유지.
- 녹음 중 메뉴바 마이크 표시가 노출됨(동료가 인지 가능) — 숨기지 말 것.
- 전부 로컬·네트워크 미사용 원칙 유지. 외부 API/클라우드 STT/LLM 도입 금지(사용자 결정).

---

## 8. (구버전 기록) 초기 프로토타입 코드 메모

> ⚠️ 아래 8·9절은 **rumps + Ollama 기반 초기 설계의 기록**이다. 현재 코드는 위 0~6절의
> pywebview + llama-cpp-python 구조로 이미 생성·검증되어 있으니, 신규 작업은 실제 파일
> (`seam_voice/`)과 0~6절을 기준으로 한다. 이 절은 의사결정 이력 보존용.

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
