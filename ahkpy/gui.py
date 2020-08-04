import dataclasses as dc
import enum
import queue
import threading
from typing import Callable

import _ahk  # noqa

__all__ = [
    "CoordMode",
    "MessageHandler",
    "ToolTip",
    "message_box",
    "on_message",
]


NOTSET = object()


class CoordMode(enum.Enum):
    SCREEN = 'screen'
    WINDOW = 'window'
    CLIENT = 'client'


coord_mode_lock = threading.RLock()


def message_box(text=None, title="", options=0, timeout=None):
    if text is None:
        # Show "Press OK to continue."
        return _ahk.call("MsgBox")

    return _ahk.call("MsgBox", options, title, str(text), timeout)
    # XXX: Return result of IfMsgBox?


def on_message(msg_number, func=None, *, max_threads=1, prepend_handler=False):
    if max_threads is not None and max_threads <= 0:
        raise ValueError("max_threads must be positive")

    if prepend_handler:
        max_threads *= -1

    def on_message_decorator(func):
        _ahk.call("OnMessage", int(msg_number), func, max_threads)
        return MessageHandler(msg_number, func)

    if func is None:
        return on_message_decorator
    return on_message_decorator(func)


@dc.dataclass(frozen=True)
class MessageHandler:
    msg_number: int
    func: Callable
    __slots__ = tuple(__annotations__.keys())

    def unregister(self):
        # TODO: Remove self.func from CALLBACKS and WRAPPED_PYTHON_FUNCTIONS in AHK.
        _ahk.call("OnMessage", self.msg_number, self.func, 0)


@dc.dataclass
class ToolTip:
    text: str = None
    x: int = None
    y: int = None
    coord_mode: CoordMode = CoordMode.WINDOW
    _id: int = dc.field(default=None, init=False, repr=False)

    _pool = queue.LifoQueue(maxsize=20)
    for tooltip_id in range(20, 0, -1):
        _pool.put(tooltip_id)
    del tooltip_id

    def __init__(self, text=None, x=None, y=None, coord_mode=CoordMode.WINDOW):
        # Write the __init__ method for code suggestions.
        self.text = text
        self.x = x
        self.y = y
        self.coord_mode = coord_mode

    def show(self, text=None, x=NOTSET, y=NOTSET, coord_mode=None):
        if not text and not self.text:
            raise ValueError("text must not be empty")
        elif text:
            self.text = text

        if x is not NOTSET:
            self.x = x
        if y is not NOTSET:
            self.y = y
        x = self.x if self.x is not None else ""
        y = self.y if self.y is not None else ""

        if coord_mode is not None:
            if isinstance(coord_mode, str):
                coord_mode = CoordMode(coord_mode.lower())
            self.coord_mode = coord_mode

        tooltip_id = self._acquire()
        with coord_mode_lock:
            _ahk.call("CoordMode", "ToolTip", self.coord_mode.value)
            _ahk.call("ToolTip", str(self.text), x, y, tooltip_id)

    def hide(self):
        if self._id is None:
            return
        _ahk.call("ToolTip", "", "", "", self._id)
        self._release()

    def _acquire(self):
        if self._id is None:
            try:
                self._id = ToolTip._pool.get_nowait()
            except queue.Empty:
                raise RuntimeError("cannot show more than 20 tooltips simultaneously") from None
        return self._id

    def _release(self):
        if self._id is None:
            return
        try:
            ToolTip._pool.put_nowait(self._id)
        except queue.Full:
            raise RuntimeError("tooltip pool is corrupted") from None
        self._id = None