# seam-voice

사무실 자리에서 오가는 대화를 **전부 로컬로** 녹음·받아쓰기·요약하는 macOS 데스크톱 앱.
네트워크를 쓰지 않으며(외부 STT/LLM 금지), 받아쓰기는 faster-whisper, 분류·요약은
**llama-cpp-python(인프로세스 GGUF)** 로 한다 — Ollama 같은 별도 데몬이 필요 없다.

UI는 **pywebview**(웹 UI를 macOS WKWebView에 표시)이고, **PyInstaller**로 더블클릭
실행하는 단일 `seam-voice.app` 으로 패키징한다.

## 구조

```
main.py             # 실행/패키징 진입점(launcher) — 절대 import 로 상대 import 보장
seam_voice/
├─ app.py            # pywebview 윈도우 + JS↔Python 브리지(Api) + 자동처리 스케줄러
├─ core/             # UI 비의존 코어
│  ├─ paths.py       # 번들/사용자 경로(개발·동결 모두 대응)
│  ├─ settings.py    # config 로드·저장 + 스케줄/일시정지/AC전원
│  ├─ recorder.py    # webrtcvad 발화 구간만 WAV 저장(백그라운드 스레드)
│  ├─ llm.py         # llama-cpp-python 래퍼(첫 실행 시 모델 다운로드)
│  ├─ processor.py   # faster-whisper 받아쓰기 → 분류 → 요약 → 리포트 → 정리
│  └─ config.yaml    # 기본 설정(앱 첫 실행 시 사용자 위치로 복사됨)
├─ tray.py           # macOS 메뉴바(NSStatusItem) 상주 — 창 닫아도 녹음 유지
└─ webui/            # index.html / style.css / app.js
```

**메뉴바 상주**: 창의 닫기 버튼을 눌러도 종료되지 않고 **숨김**되며 녹음/스케줄은 계속된다
(pywebview `closing` 이벤트를 취소하고 hide). 제어는 메뉴바 아이콘(🎙️ 녹음·시간대 / 🔴 대기 /
⏸ 일시정지 / ⚪️ 정지)의 메뉴로 한다: 창 열기·숨기기, 녹음 시작/정지, 일시정지(15/30/60/해제),
지금 처리, 종료. 기본은 Dock 아이콘 없는 메뉴바 전용(`ui.dock_icon`).

데이터(기본 `~/seam-voice-data`, `config.yaml`의 `storage.base_dir`로 변경):

- `raw_audio/YYYY-MM-DD/HH-MM-SS_Ns.wav` — 발화 구간 (7일 후 삭제)
- `reports/YYYY-MM-DD.md` — 받아쓰기 + 요약

설정/모델 캐시(패키지 앱):

- `~/Library/Application Support/seam-voice/config.yaml` — 사용자 설정(앱 "설정" 탭에서 편집)
- `~/Library/Application Support/seam-voice/models/` — GGUF 모델 캐시

## 개발 실행

```bash
cd /Users/minkyu/workspace/seam-voice
pip install -r requirements.txt          # webrtcvad 컴파일 필요 시: xcode-select --install
python -m seam_voice.app                 # 앱 창 실행 (첫 녹음 시 마이크 권한 허용)
```

코어 모듈 단독 실행(디버깅):

```bash
python -m seam_voice.core.recorder              # 녹음기만
python -m seam_voice.core.processor 2026-06-23  # 특정 날짜 일괄 처리
```

> 개발 중 `core/config.yaml` 변경을 바로 보려면 사용자 복사본을 지우거나
> `SEAM_VOICE_CONFIG=/path/to/config.yaml` 로 override 한다.

## 단일 .app 빌드

```bash
pip install pyinstaller
pyinstaller seam-voice.spec
open dist/seam-voice.app                  # 더블클릭 실행
```

- M4에서 빌드·기동 **검증됨**(248MB `.app`, webui·config·libllama·libggml-metal·_webrtcvad·libportaudio 동봉).
- entry 는 `main.py` 다(app.py 직접 entry 는 PyInstaller `__main__` 실행 시 상대 import 가 깨짐).
- `llama-cpp-python` 은 Apple Silicon에서 Metal 빌드로 설치돼야 GPU 오프로드(`n_gpu_layers: -1`)가 동작한다.
- 처음 실행하면 GGUF 모델(약 4.7GB)과 faster-whisper `large-v3`(약 3GB)를 다운로드한다(모델은 번들에 미포함).
- 서명 없이 배포 시 Gatekeeper가 막으므로, 본인 맥은 우클릭 → 열기. 외부 배포는 코드서명+공증 필요.

## 설정 (`config.yaml`)

| 키 | 설명 |
|---|---|
| `storage.base_dir` | 녹음/리포트 저장 위치 |
| `schedule.{days,windows,lunch}` | 녹음 허용 요일/시간대/점심 제외 |
| `audio.*` | VAD 민감도·프리롤·무음 종료·최소 구간 길이 |
| `transcription.{model,device,compute_type}` | faster-whisper 설정 |
| `llm.{model_repo,model_file,model_path,n_gpu_layers}` | 로컬 GGUF LLM |
| `retention_rules.*` | 보관 일수/용량/제3자 대화 폐기/키워드 |
| `processing.{batch_time,require_ac_power}` | 자동 처리 시각/전원 조건 |
| `ui.dock_icon` | false=메뉴바 전용(Dock 숨김), true=Dock 아이콘 표시 |
| `ui.start_recording_on_launch` | 앱 시작 시 자동 녹음 시작(상주용) |

## 프라이버시 / 법적 제약 (유지)

- 한국 통신비밀보호법: **본인이 참여한 대화** 녹음은 합법이나 **제3자 대화**는 회색지대 →
  `retention_rules.discard_non_participated`를 기본 ON으로 둔다.
- 녹음 중에는 macOS 마이크 표시가 노출돼 동료가 인지할 수 있다 — 숨기지 않는다.
- 전부 로컬·네트워크 미사용 원칙을 유지한다(모델 최초 다운로드 제외). 외부 API/클라우드 STT·LLM은 도입하지 않는다.

## 상태

M4에서 검증됨: 의존성 설치, 마이크 캡처, faster-whisper(large-v3) 받아쓰기, llama-cpp-python
(Qwen2.5-7B) 분류/요약, end-to-end 파이프라인, PyInstaller `.app` 빌드·기동, 메뉴바 상주 로직.
화자 분리(pyannote)는 미구현 스텁(기본 off). 배경·백로그는 `docs/HANDOFF.md` 참고.

## 라이선스

[MIT](LICENSE)
