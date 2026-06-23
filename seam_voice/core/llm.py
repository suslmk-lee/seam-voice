"""로컬 LLM (llama-cpp-python) — 분류/요약용. Ollama 불필요(인프로세스 GGUF).

첫 사용 시 GGUF 모델을 자동 다운로드한다(``llm.model_repo``/``model_file``,
캐시: ``~/Library/Application Support/seam-voice/models``). 직접 받은 파일을
쓰려면 ``llm.model_path`` 에 .gguf 경로를 지정한다. Apple Silicon에서는
``n_gpu_layers: -1`` 로 Metal 전체 오프로드.
"""
from __future__ import annotations

import threading

from .paths import app_support_dir


class LocalLLM:
    def __init__(self, settings):
        self.settings = settings
        self._llm = None
        self._lock = threading.Lock()
        self.status = "idle"   # idle | downloading | ready | error
        self.error = ""

    @property
    def ready(self) -> bool:
        return self._llm is not None

    def _ensure(self):
        if self._llm is not None:
            return self._llm
        with self._lock:
            if self._llm is not None:
                return self._llm
            from llama_cpp import Llama

            s = self.settings
            common = dict(
                n_ctx=int(s.get("llm.n_ctx", 8192)),
                n_gpu_layers=int(s.get("llm.n_gpu_layers", -1)),
                verbose=False,
            )
            model_path = s.get("llm.model_path") or ""
            try:
                self.status = "downloading"
                if model_path:
                    self._llm = Llama(model_path=str(model_path), **common)
                else:
                    cache = app_support_dir() / "models"
                    cache.mkdir(parents=True, exist_ok=True)
                    self._llm = Llama.from_pretrained(
                        repo_id=s.get("llm.model_repo"),
                        filename=s.get("llm.model_file"),
                        cache_dir=str(cache),
                        **common,
                    )
                self.status = "ready"
            except Exception as exc:
                self.status = "error"
                self.error = str(exc)
                raise
            return self._llm

    def generate(self, prompt: str, *, as_json: bool = False) -> str:
        llm = self._ensure()
        kwargs = dict(
            messages=[{"role": "user", "content": prompt}],
            temperature=float(self.settings.get("llm.temperature", 0.2)),
            max_tokens=int(self.settings.get("llm.max_tokens", 1024)),
        )
        if as_json:
            kwargs["response_format"] = {"type": "json_object"}
        out = llm.create_chat_completion(**kwargs)
        return out["choices"][0]["message"]["content"]

    def preload(self) -> None:
        """백그라운드에서 모델 준비(다운로드/로드). 실패는 status/error에 기록."""
        try:
            self._ensure()
        except Exception:
            pass
