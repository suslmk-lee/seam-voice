# -*- mode: python ; coding: utf-8 -*-
# seam-voice PyInstaller 스펙 — 단일 .app 번들 생성.
#   빌드:  pyinstaller seam-voice.spec
#   결과:  dist/seam-voice.app   (더블클릭 실행)
#
# 무거운 네이티브 패키지(llama_cpp, ctranslate2, faster_whisper)와 pywebview(pyobjc)는
# collect_all 로 데이터/바이너리/숨은 import 를 함께 끌어온다. webui/ 와 기본 config.yaml
# 은 datas 로 동봉되며, 런타임에서 paths.resource_path() 가 동일 상대경로로 찾는다.
from PyInstaller.utils.hooks import collect_all

datas = [
    ("seam_voice/webui", "webui"),
    ("seam_voice/core/config.yaml", "core"),
]
binaries = []
hiddenimports = ["webview.platforms.cocoa"]

for pkg in ("llama_cpp", "ctranslate2", "faster_whisper", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["seam_voice/app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="seam-voice",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="seam-voice",
)
app = BUNDLE(
    coll,
    name="seam-voice.app",
    icon=None,
    bundle_identifier="ai.quantumcns.seamvoice",
    info_plist={
        "CFBundleShortVersionString": "0.1.0",
        "NSMicrophoneUsageDescription": "사무실 대화를 로컬로 녹음·받아쓰기합니다.",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    },
)
