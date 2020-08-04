import dataclasses as dc
import enum
import threading

import _ahk  # noqa

from . import colors
from . import keys
from .exceptions import Error

__all__ = [
    "Control",
    "ExWindowStyle",
    "Window",
    "WindowHotkeyContext",
    "Windows",
    "WindowStyle",
    "all_windows",
    "detect_hidden_text",
    "set_title_match_mode",
    "set_win_delay",
    "visible_windows",
    "windows",
]


last_found_window_lock = threading.RLock()
detect_hidden_windows_lock = threading.RLock()


def detect_hidden_text(value):
    # TODO: Make this setting thread-local.
    value = "On" if value else "Off"
    _ahk.call("DetectHiddenText", value)


def set_title_match_mode(mode=None, speed=None):
    # TODO: Make this setting thread-local.
    if mode is not None:
        match_modes = {
            "startswith": "1",
            "contains": "2",
            "exact": "3",
            "1": "1",
            "2": "2",
            "3": "3",
            "regex": "regex",
        }
        ahk_mode = match_modes.get(str(mode).lower())
        if ahk_mode is None:
            raise ValueError(f"unknown match mode {mode!r}")
        _ahk.call("SetTitleMatchMode", ahk_mode)

    if speed is not None:
        speeds = ["fast", "slow"]
        if speed.lower() not in speeds:
            raise ValueError(f"unknown speed {speed!r}")
        _ahk.call("SetTitleMatchMode", speed)


def set_win_delay(value):
    # TODO: Make this setting thread-local.
    if value is None:
        value = -1
    else:
        value *= 1000
    _ahk.call("SetWinDelay", value)


@dc.dataclass(frozen=True)
class Windows:
    title: str = None
    class_name: str = None
    id: int = None
    pid: int = None
    exe: str = None
    text: str = None
    exclude_title: str = None
    exclude_text: str = None
    exclude_hidden_windows: bool = True

    def filter(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        # XXX: Consider adding the "detect_hidden_text" parameter.
        # XXX: Consider adding the "title_match_mode" parameter.
        # TODO: Filtering by an attribute of a null-window matches all the windows:
        #
        #     null_win = ahk.windows.first(id=99999)
        #     assert not null_win
        #     assert null_win.title is None
        #     len(ahk.windows.filter(title=null_win.title))  # len > 0
        #

        if title is None and class_name is None and id is None and pid is None and exe is None and text is None:
            return self
        return dc.replace(
            self,
            title=default(title, self.title),
            class_name=default(class_name, self.class_name),
            id=default(id, self.id),
            pid=default(pid, self.pid),
            exe=default(exe, self.exe),
            text=default(text, self.text),
        )

    def exclude(self, title=None, *, text=None, hidden_windows=None):
        # XXX: Consider implementing class_name, id, pid, and exe exclusion in
        # Python.
        if title is None and text is None and hidden_windows is None:
            return self
        return dc.replace(
            self,
            exclude_title=default(title, self.exclude_title),
            exclude_text=default(text, self.exclude_text),
            exclude_hidden_windows=default(hidden_windows, self.exclude_hidden_windows),
        )

    def exist(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        win_id = self._call("WinExist", *self._query())
        return Window(win_id)

    first = exist
    top = exist

    def last(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        win_id = self._call("WinGet", "IDLast", *self._query())
        return Window(win_id)

    bottom = last

    def get_active(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        query = self._query()
        if query == ("", "", "", ""):
            query = ("A", "", "", "")
        win_id = self._call("WinActive", *query)
        return Window(win_id)

    def wait(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._wait("WinWait", timeout)

    def wait_active(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._wait("WinWaitActive", timeout)

    def wait_inactive(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._wait("WinWaitNotActive", timeout)

    def wait_close(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        # WinWaitClose doesn't set Last Found Window, return False if the wait
        # was timed out.
        timed_out = self._call("WinWaitClose", *self._include(), timeout or "", *self._exclude())
        return not timed_out

    def _wait(self, cmd, timeout):
        # Calling WinWait[Not]Active and WinWait sets an implicit Last Found
        # Window that is local to the current AHK thread. Let's retrieve it
        # while protecting it from being overwritten by other Python threads.
        with last_found_window_lock:
            timed_out = self._call(cmd, *self._include(), timeout or "", *self._exclude())
            if timed_out:
                return Window(0)
            # Return the Last Found Window.
            return windows.first()

    def activate(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinActivate", *self._query())
        if timeout is not None:
            return self.wait_active(timeout=timeout)

    def close(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinClose", *self._include(), timeout, *self._exclude())

    def hide(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinHide", *self._query())

    def kill(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinKill", *self._include(), timeout, *self._exclude())

    def maximize(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinMaximize", *self._query())

    def minimize(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinMinimize", *self._query())

    def restore(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinRestore", *self._query())

    def show(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinShow", *self._query())

    def pin_to_top(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinSet", "AlwaysOnTop", "On", *self._query())

    def unpin_from_top(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinSet", "AlwaysOnTop", "Off", *self._query())

    def toggle_always_on_top(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinSet", "AlwaysOnTop", "Toggle", *self._query())

    def bring_to_top(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinSet", "Top", "", *self._query())

    def send_to_bottom(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinSet", "Bottom", "", *self._query())

    def disable(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinSet", "Disable", "", *self._query())

    def enable(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinSet", "Enable", "", *self._query())

    def redraw(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._call("WinSet", "Redraw", "", *self._query())

    def close_all(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._group_action("WinClose", timeout)

    def hide_all(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._group_action("WinHide")

    def kill_all(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None, timeout=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._group_action("WinKill", timeout)

    def maximize_all(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._group_action("WinMaximize")

    def minimize_all(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._group_action("WinMinimize")

    # TODO: Implement WinMinimizeAllUndo.

    def restore_all(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._group_action("WinRestore")

    def show_all(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        self._group_action("WinShow")

    def _group_action(self, cmd, timeout=None):
        if self == Windows() and cmd == "WinMinimize":
            # If the filter matches all the windows, minimize everything except
            # the desktop window.
            self._call("WinMinimizeAll")
            return

        query_hash = hash(self)
        query_hash_str = str(query_hash).replace("-", "m")  # AHK doesn't allow "-" in group names
        label = ""
        self._call("GroupAdd", query_hash_str, *self._include(), label, *self._exclude())
        self._call(cmd, f"ahk_group {query_hash_str}", "", timeout)
        if timeout is not None:
            return not self.exist()

    def window_context(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._hotkey_context("IfWinExist", lambda: self.exist())

    def nonexistent_window_context(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._hotkey_context("IfWinNotExist", lambda: not self.exist())

    def active_window_context(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._hotkey_context("IfWinActive", lambda: self.get_active())

    def inactive_window_context(self, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        return self._hotkey_context("IfWinNotActive", lambda: not self.get_active())

    def _hotkey_context(self, cmd, predicate):
        if self._exclude() != ("", ""):
            # The Hotkey, IfWin command doesn't support excluding windows, let's
            # implement it.
            return keys.HotkeyContext(predicate)

        return WindowHotkeyContext(cmd, *self._include())

    def send(self, keys, title=None, *, class_name=None, id=None, pid=None, exe=None, text=None):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text)
        control = ""
        self._call("ControlSend", control, str(keys), *self._query())

    def __iter__(self):
        """Return matching windows ordered from top to bottom."""
        win_ids = self._call("WinGet", "List", *self._query())
        for win_id in win_ids.values():
            yield Window(win_id)

    def __len__(self):
        return self._call("WinGet", "Count", *self._query())

    def __repr__(self):
        field_strs = [
            f"{field_name}={value!r}"
            for field_name, value in dc.asdict(self).items()
            if value is not None
        ]
        return self.__class__.__qualname__ + f"({', '.join(field_strs)})"

    def _call(self, cmd, *args):
        with detect_hidden_windows_lock:
            if self.exclude_hidden_windows:
                _ahk.call("DetectHiddenWindows", "Off")
            else:
                _ahk.call("DetectHiddenWindows", "On")
            return _ahk.call(cmd, *args)

    def _query(self):
        return (*self._include(), *self._exclude())

    def _include(self):
        parts = []
        if self.title is not None:
            parts.append(str(self.title))
        if self.class_name is not None:
            parts.append(f"ahk_class {self.class_name}")
        if self.id is not None:
            parts.append(f"ahk_id {self.id}")
        if self.pid is not None:
            parts.append(f"ahk_pid {self.pid}")
        if self.exe is not None:
            parts.append(f"ahk_exe {self.exe}")

        return (
            " ".join(parts),
            default(str, self.text, ""),
        )

    def _exclude(self):
        return (
            default(str, self.exclude_title, ""),
            default(str, self.exclude_text, ""),
        )


windows = visible_windows = Windows()
all_windows = Windows(exclude_hidden_windows=False)


@dc.dataclass(frozen=True)
class _Window:
    # I'd like the Window and Control class to be hashable, and making the
    # dataclass frozen also makes it hashable. However, frozen dataclasses
    # cannot have setter properties unless it's a subclass.

    id: int

    def __bool__(self):
        return self.id != 0

    def _call(self, cmd, *args, exclude_hidden_windows=False):
        # Call the command only if the window was found previously. This makes
        # optional chaining possible. For example,
        # `ahk.windows.first(class_name="Notepad").close()` doesn't error out
        # when there are no Notepad windows.
        if self.id == 0:
            return
        with detect_hidden_windows_lock:
            if exclude_hidden_windows:
                _ahk.call("DetectHiddenWindows", "Off")
            else:
                _ahk.call("DetectHiddenWindows", "On")
            return _ahk.call(cmd, *args)

    def _include(self):
        win_text = ""
        return f"ahk_id {self.id}", win_text


class Window(_Window):
    @property
    def rect(self):
        result = self._call("WinGetPos", *self._include())
        return result["X"], result["Y"], result["Width"], result["Height"]

    @rect.setter
    def rect(self, new_rect):
        x, y, width, height = new_rect
        self.move(x, y, width, height)

    @property
    def position(self):
        x, y, _, _ = self.rect
        return x, y

    @position.setter
    def position(self, new_position):
        x, y = new_position
        self.move(x, y)

    @property
    def x(self):
        x, _, _, _ = self.rect
        return x

    @x.setter
    def x(self, new_x):
        self.move(x=new_x)

    @property
    def y(self):
        _, y, _, _ = self.rect
        return y

    @y.setter
    def y(self, new_y):
        self.move(y=new_y)

    @property
    def width(self):
        _, _, width, _ = self.rect
        return width

    @width.setter
    def width(self, new_width):
        self.move(width=new_width)

    @property
    def height(self):
        _, _, _, height = self.rect
        return height

    @height.setter
    def height(self, new_height):
        self.move(height=new_height)

    def move(self, x=None, y=None, width=None, height=None):
        self._call("WinMove",
                   *self._include(),
                   default(int, x, ""),
                   default(int, y, ""),
                   default(int, width, ""),
                   default(int, height, ""))

    @property
    def is_active(self):
        return self._call("WinActive", *self._include()) != 0

    @property
    def exists(self):
        return self._call("WinExist", *self._include()) != 0

    @property
    def class_name(self):
        return self._call("WinGetClass", *self._include())

    @property
    def text(self):
        return self._call("WinGetText", *self._include())

    @property
    def title(self):
        return self._call("WinGetTitle", *self._include())

    @title.setter
    def title(self, new_title):
        return self._call("WinSetTitle", *self._include(), str(new_title))

    @property
    def pid(self):
        return self._get("PID")

    @property
    def process_name(self):
        return self._get("ProcessName")

    @property
    def process_path(self):
        return self._get("ProcessPath")

    @property
    def is_minimized(self):
        min_max = self._get("MinMax")
        if min_max is not None:
            return min_max == -1

    @is_minimized.setter
    def is_minimized(self, value):
        if value:
            self.minimize()
        else:
            self.restore()

    def toggle_minimized(self):
        is_minimized = self.is_minimized
        if is_minimized is not None:
            self.is_minimized = not is_minimized

    @property
    def is_restored(self):
        min_max = self._get("MinMax")
        if min_max is not None:
            return min_max == 0

    @property
    def is_maximized(self):
        min_max = self._get("MinMax")
        if min_max is not None:
            return min_max == 1

    @is_maximized.setter
    def is_maximized(self, value):
        if value:
            self.maximize()
        else:
            self.restore()

    def toggle_maximized(self):
        is_maximized = self.is_maximized
        if is_maximized is not None:
            self.is_maximized = not is_maximized

    # TODO: Add control methods to Windows

    def control_class_names(self):
        return self._get("ControlList").splitlines()

    def controls(self):
        hwnds = self._get("ControlListHwnd").splitlines()
        return [
            Control(int(hwnd, base=16))
            for hwnd in hwnds
        ]

    def get_control(self, class_name):
        control_id = self._call("ControlGet", "Hwnd", "", class_name, *self._include())
        return Control(control_id)

    @property
    def always_on_top(self):
        if self.ex_style is not None:
            return ExWindowStyle.TOPMOST in self.ex_style

    @always_on_top.setter
    def always_on_top(self, value):
        if value:
            self.pin_to_top()
        else:
            self.unpin_from_top()

    def pin_to_top(self):
        self._set("AlwaysOnTop", "On")

    def unpin_from_top(self):
        self._set("AlwaysOnTop", "Off")

    def toggle_always_on_top(self):
        self._set("AlwaysOnTop", "Toggle")

    def send_to_bottom(self):
        self._set("Bottom")

    def bring_to_top(self):
        self._set("Top")

    def disable(self):
        self._set("Disable")

    def enable(self):
        self._set("Enable")

    @property
    def is_enabled(self):
        style = self.style
        if style is not None:
            return WindowStyle.DISABLED not in style

    @is_enabled.setter
    def is_enabled(self, value):
        if value:
            self.enable()
        else:
            self.disable()

    def redraw(self):
        self._set("Redraw")

    def set_region(self, options):
        # TODO: Implement better options.
        self._set("Region", options)

    def reset_region(self):
        self._set("Region", "")

    @property
    def style(self):
        style = self._get("Style")
        if style is not None:
            return WindowStyle(style)

    @style.setter
    def style(self, value):
        self._set("Style", int(value))

    @property
    def ex_style(self):
        ex_style = self._get("ExStyle")
        if ex_style is not None:
            return ExWindowStyle(ex_style)

    @ex_style.setter
    def ex_style(self, value):
        self._set("ExStyle", int(value))

    @property
    def opacity(self):
        return self._get("Transparent")

    @opacity.setter
    def opacity(self, value):
        if value is None:
            ahk_value = "Off"
        elif not 0 <= value <= 255:
            raise ValueError("opacity value must be between 0 and 255")
        else:
            ahk_value = int(value)
        self._set("Transparent", ahk_value)

    @property
    def transparent_color(self):
        result = self._get("TransColor")
        if result is not None:
            hex_color = hex(result)[2:]
            return colors.to_tuple(hex_color)

    @transparent_color.setter
    def transparent_color(self, value):
        if value is None:
            ahk_value = "Off"
        else:
            r, g, b = value
            ahk_value = colors.to_hex(r, g, b)
        self._set("TransColor", ahk_value)

    def hide(self):
        self._call("WinHide", *self._include())

    def show(self):
        self._call("WinShow", *self._include())

    @property
    def is_visible(self):
        style = self.style
        if style is not None:
            return WindowStyle.VISIBLE in style

    @is_visible.setter
    def is_visible(self, value):
        if value:
            self.show()
        else:
            self.hide()

    def activate(self, timeout=None):
        self._call("WinActivate", *self._include())
        if timeout is not None:
            return self.wait_active(timeout=timeout)

    def get_status_bar_text(self, part=1):
        return self._call("StatusBarGetText", int(part), *self._include())

    def wait_status_bar(self, bar_text="", timeout=None, part=1, interval=0.05):
        timed_out = self._call(
            "StatusBarWait",
            bar_text,
            default(timeout, ""),
            part,
            *self._include(),
            interval * 1000,
        )
        return not timed_out

    def close(self, timeout=None):
        self._call("WinClose", *self._include(), timeout)
        if timeout is not None:
            # TODO: Test timeout.
            return not self.exists

    def kill(self, timeout=None):
        self._call("WinKill", *self._include(), timeout)
        if timeout is not None:
            # TODO: Test timeout.
            return not self.exists

    def maximize(self):
        self._call("WinMaximize", *self._include())

    def minimize(self):
        self._call("WinMinimize", *self._include())

    def restore(self):
        self._call("WinRestore", *self._include())

    def wait_active(self, timeout=None):
        timed_out = self._call("WinWaitActive", *self._include(), timeout)
        return not timed_out

    def wait_inactive(self, timeout=None):
        timed_out = self._call("WinWaitNotActive", *self._include(), timeout)
        return not timed_out

    def wait_hidden(self, timeout=None):
        timed_out = self._call("WinWaitClose", *self._include(), timeout, exclude_hidden_windows=True)
        return not timed_out

    def wait_close(self, timeout=None):
        timed_out = self._call("WinWaitClose", *self._include(), timeout)
        return not timed_out

    def send(self, keys):
        control = ""
        self._call("ControlSend", control, str(keys), *self._include())

    def send_message(self, msg, w_param, l_param, timeout=5):
        control = exclude_title = exclude_text = ""
        try:
            result = self._call(
                "SendMessage", int(msg), int(w_param), int(l_param), control,
                *self._include(), exclude_title, exclude_text,
                int(timeout * 1000),
            )
        except Error:
            raise RuntimeError("there was a problem sending message or response timed out") from None
        return result

    def post_message(self, msg, w_param, l_param):
        control = ""
        err = self._call("PostMessage", int(msg), int(w_param), int(l_param), control, *self._include())
        return not err

    def _get(self, subcmd):
        result = self._call("WinGet", subcmd, *self._include())
        if result != "":
            return result

    def _set(self, subcmd, value=""):
        return self._call("WinSet", subcmd, value, *self._include())


class Control(_Window):
    @property
    def text(self):
        return self._call("ControlGetText", "", *self._include())

    @text.setter
    def text(self, value):
        return self._call("ControlSetText", "", value, *self._include())

    def _get(self, subcmd, value=""):
        result = self._call("ControlGet", subcmd, value, "", *self._include())
        if result != "":
            return result


@dc.dataclass(frozen=True)
class WindowHotkeyContext(keys.BaseHotkeyContext):
    # FIXME: Title and text have different modes that depend on global config.
    # This makes win_title and win_text not enough to identify the context.
    cmd: str
    win_title: str
    win_text: str

    def _enter(self):
        _ahk.call("HotkeyWinContext", self.cmd, self.win_title, self.win_text)

    def _exit(self):
        _ahk.call("HotkeyExitContext")


class WindowStyle(enum.IntFlag):
    BORDER = 0x00800000
    CAPTION = 0x00C00000
    CHILD = 0x40000000
    CHILDWINDOW = 0x40000000
    CLIPCHILDREN = 0x02000000
    CLIPSIBLINGS = 0x04000000
    DISABLED = 0x08000000
    DLGFRAME = 0x00400000
    GROUP = 0x00020000
    HSCROLL = 0x00100000
    ICONIC = 0x20000000
    MAXIMIZE = 0x01000000
    MAXIMIZEBOX = 0x00010000
    MINIMIZE = 0x20000000
    MINIMIZEBOX = 0x00020000
    OVERLAPPED = 0x00000000
    SYSMENU = 0x00080000
    THICKFRAME = 0x00040000
    OVERLAPPEDWINDOW = (OVERLAPPED | CAPTION | SYSMENU | THICKFRAME | MINIMIZEBOX | MAXIMIZEBOX)
    POPUP = 0x80000000
    POPUPWINDOW = (POPUP | BORDER | SYSMENU)
    SIZEBOX = 0x00040000
    TABSTOP = 0x00010000
    TILED = 0x00000000
    TILEDWINDOW = (OVERLAPPED | CAPTION | SYSMENU | THICKFRAME | MINIMIZEBOX | MAXIMIZEBOX)
    VISIBLE = 0x10000000
    VSCROLL = 0x00200000


class ExWindowStyle(enum.IntFlag):
    ACCEPTFILES = 0x00000010
    APPWINDOW = 0x00040000
    CLIENTEDGE = 0x00000200
    COMPOSITED = 0x02000000
    CONTEXTHELP = 0x00000400
    CONTROLPARENT = 0x00010000
    DLGMODALFRAME = 0x00000001
    LAYERED = 0x00080000
    LAYOUTRTL = 0x00400000
    LEFT = 0x00000000
    LEFTSCROLLBAR = 0x00004000
    LTRREADING = 0x00000000
    MDICHILD = 0x00000040
    NOACTIVATE = 0x08000000
    NOINHERITLAYOUT = 0x00100000
    NOPARENTNOTIFY = 0x00000004
    NOREDIRECTIONBITMAP = 0x00200000
    TOOLWINDOW = 0x00000080
    TOPMOST = 0x00000008
    WINDOWEDGE = 0x00000100
    OVERLAPPEDWINDOW = (WINDOWEDGE | CLIENTEDGE)
    PALETTEWINDOW = (WINDOWEDGE | TOOLWINDOW | TOPMOST)
    RIGHT = 0x00001000
    RIGHTSCROLLBAR = 0x00000000
    RTLREADING = 0x00002000
    STATICEDGE = 0x00020000
    TRANSPARENT = 0x00000020


def identity(a):
    return a


def default(a, b, func=identity):
    if func is not identity:
        func, a, b = a, b, func
    if a is not None:
        return func(a)
    return b