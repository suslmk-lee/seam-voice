"""macOS 메뉴바(트레이) 상주 — pywebview 와 같은 프로세스/메인 스레드에서 운용.

pywebview 가 Cocoa 런루프를 점유하므로 별도 트레이 라이브러리(pystray/rumps)와는
메인 루프가 충돌한다. 대신 pyobjc 로 같은 NSApplication 에 NSStatusItem 을 직접 붙인다.

- 창의 빨간 닫기 버튼 → 종료가 아니라 **숨김**(녹음 계속). pywebview ``closing`` 이벤트에서
  ``False`` 를 반환해 실제 닫힘(=마지막 창 닫힘 시 app.stop_)을 취소하고 orderOut 으로 숨긴다.
- 트레이 메뉴(창 열기/숨기기, 녹음 시작·정지, 일시정지, 지금 처리, 종료)로 전부 제어.
- 3초 타이머로 상태 아이콘 갱신(🎙️/🔴/⏸/⚪️).
- "종료"는 ``_quitting`` 플래그를 세워 closing 핸들러가 닫힘을 허용하게 한 뒤 terminate.
"""
from __future__ import annotations

import AppKit
import objc

_refs: dict = {}   # GC 방지용 강참조 보관


class _TrayController(AppKit.NSObject):
    def initWithApi_window_(self, api, window):
        self = objc.super(_TrayController, self).init()
        if self is None:
            return None
        self._api = api
        self._window = window
        self._statusitem = None
        self._visible = True
        self._quitting = False
        return self

    # ---- 창 ----
    def toggleWindow_(self, sender):
        if self._visible:
            self._window.hide()
            self._visible = False
        else:
            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self._window.show()
            self._visible = True

    def note_hidden(self):
        self._visible = False

    # ---- 녹음/일시정지 ----
    def startRecording_(self, sender):
        self._api.start_recording()

    def stopRecording_(self, sender):
        self._api.stop_recording()

    def pause15_(self, sender):
        self._api.pause(15)

    def pause30_(self, sender):
        self._api.pause(30)

    def pause60_(self, sender):
        self._api.pause(60)

    def resumeRecording_(self, sender):
        self._api.resume()

    # ---- 처리/종료 ----
    def processNow_(self, sender):
        self._api.process_now()

    def quitApp_(self, sender):
        self._quitting = True
        try:
            self._api.stop_recording()
        except Exception:
            pass
        AppKit.NSApplication.sharedApplication().terminate_(None)

    # ---- 상태 아이콘 ----
    def tick_(self, timer):
        try:
            paused = self._api.settings.is_paused()
            recording = self._api._recording()
            within = self._api.settings.is_within_schedule()
        except Exception:
            return
        if paused:
            title = "⏸"
        elif recording and within:
            title = "🎙️"
        elif recording:
            title = "🔴"
        else:
            title = "⚪️"
        if self._statusitem is not None:
            self._statusitem.button().setTitle_(title)


def setup_tray(api, window, *, dock_icon: bool = False):
    app = AppKit.NSApplication.sharedApplication()
    # 메뉴바 전용(Dock 숨김) vs Dock 아이콘 표시
    app.setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyRegular
        if dock_icon
        else AppKit.NSApplicationActivationPolicyAccessory
    )

    controller = _TrayController.alloc().initWithApi_window_(api, window)

    bar = AppKit.NSStatusBar.systemStatusBar()
    item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
    item.button().setTitle_("⚪️")
    controller._statusitem = item

    def add(menu, title, sel):
        mi = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
        mi.setTarget_(controller)
        menu.addItem_(mi)
        return mi

    def sep(menu):
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

    menu = AppKit.NSMenu.alloc().init()
    add(menu, "창 열기/숨기기", "toggleWindow:")
    sep(menu)
    add(menu, "녹음 시작", "startRecording:")
    add(menu, "녹음 정지", "stopRecording:")

    pause_parent = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("일시정지", None, "")
    pause_menu = AppKit.NSMenu.alloc().init()
    add(pause_menu, "15분", "pause15:")
    add(pause_menu, "30분", "pause30:")
    add(pause_menu, "60분", "pause60:")
    add(pause_menu, "해제", "resumeRecording:")
    pause_parent.setSubmenu_(pause_menu)
    menu.addItem_(pause_parent)

    sep(menu)
    add(menu, "지금 일괄 처리", "processNow:")
    sep(menu)
    add(menu, "종료", "quitApp:")
    item.setMenu_(menu)

    # 창 닫기 → 숨김(상주). 단 '종료' 중이면 실제 닫힘 허용.
    def on_closing():
        if controller._quitting:
            return None
        window.hide()
        controller.note_hidden()
        return False

    window.events.closing += on_closing

    # 상태 아이콘 타이머(메인 런루프)
    timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        3.0, controller, "tick:", None, True
    )

    _refs.update(
        controller=controller, item=item, menu=menu,
        pause_menu=pause_menu, timer=timer, closing=on_closing,
    )
    return controller
