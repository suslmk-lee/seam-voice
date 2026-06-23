"""실행/패키징 진입점.

``seam_voice.app`` 을 **절대 import** 해서, app.py 내부의 패키지 상대 import
(``from .core import ...``)가 패키지 컨텍스트에서 정상 동작하게 한다. PyInstaller 가
스크립트를 ``__main__`` 으로 실행할 때 상대 import 가 깨지는 문제를 이 launcher 로 회피한다.
spec 의 Analysis entry 도 이 파일을 가리킨다.

개발 실행은 ``python -m seam_voice.app`` 또는 ``python main.py`` 모두 가능.
"""
from seam_voice.app import main

if __name__ == "__main__":
    main()
