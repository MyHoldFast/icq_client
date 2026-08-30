import re
import os
import tkinter as tk
from typing import Dict, List, Tuple

from resources import TRAY_AVAILABLE, get_resource_path

_SMILEY_MAP_RAW: List[Tuple[str, List[str]]] = [
    ("aa", ["O:-)", "O=)"]),
    ("ab", [":-)",":-)",":)","=)"]),
    ("ac", [":-(",":(", ";("]),
    ("ad", [";-)", ";)"]),
    ("ae", [":-P"]),
    ("af", ["8-)"]),
    ("ag", [":-D"]),
    ("ah", [":-["]),
    ("ai", ["=-O"]),
    ("aj", [":-*"]),
    ("ak", [":'("]),
    ("al", [":-X", ":-x"]),
    ("am", [">:o"]),
    ("an", [":-|"]),
    ("ao", [":-\\", ":-/"]),
    ("ap", ["*JOKINGLY*"]),
    ("aq", ["]:->"] ),
    ("ar", ["[:-}"]),
    ("as", ["*KISSED*"]),
    ("at", [":-!"]),
    ("au", ["*TIRED*"]),
    ("av", ["*STOP*"]),
    ("aw", ["*KISSING*"]),
    ("ax", ["@}->--"]),
    ("ay", ["*THUMBS UP*"]),
    ("az", ["*DRINK*"]),
    ("ba", ["*IN LOVE*"]),
    ("bb", ["@="]),
    ("bc", ["*HELP*"]),
    ("bd", ["\\m/"]),
    ("be", ["%)"]),
    ("bf", ["*OK*"]),
    ("bg", ["*WASSUP*", "*SUP*"]),
    ("bh", ["*SORRY*"]),
    ("bi", ["*BRAVO*"]),
    ("bj", ["*ROFL*", "*LOL*"]),
    ("bk", ["*PARDON*"]),
    ("bl", ["*NO*"]),
    ("bm", ["*CRAZY*"]),
    ("bn", ["*DONT_KNOW*", "*UNKNOWN*"]),
    ("bo", ["*DANCE*"]),
    ("bp", ["*YAHOO*", "*YAHOO!*"]),
    ("bq", ["*HI*", "*PREVED*", "*PRIVET*", "*HELLO*"]),
    ("br", ["*BYE*"]),
    ("bs", ["*YES*"]),
    ("bt", [";D", "*ACUTE*"]),
    ("bu", ["*WALL*", "*DASH*"]),
    ("bv", ["*WRITE*", "*MAIL*"]),
    ("bw", ["*SCRATCH*"]),
]

_CODE_TO_FILE: Dict[str, str] = {}
_SMILEY_CODES: List[str] = []

def _init_smiley_codes():
    for fname, codes in _SMILEY_MAP_RAW:
        for code in codes:
            _CODE_TO_FILE[code] = fname
    _SMILEY_CODES.extend(sorted(_CODE_TO_FILE.keys(), key=len, reverse=True))

_init_smiley_codes()

def _build_smiley_re() -> re.Pattern:
    parts = [re.escape(c) for c in _SMILEY_CODES]
    return re.compile("(" + "|".join(parts) + ")")

_SMILEY_RE: re.Pattern = _build_smiley_re()

_GIF_FRAMES_CACHE: Dict[str, list] = {}
_GIF_DELAYS_CACHE: Dict[str, list] = {}

_SMILEYS_DIR = get_resource_path("smiles")

def _load_gif_frames(filename: str) -> Tuple[list, List[int]]:
    if filename in _GIF_FRAMES_CACHE:
        return _GIF_FRAMES_CACHE[filename], _GIF_DELAYS_CACHE[filename]
    if not _SMILEYS_DIR:
        return [], []
    path = os.path.join(_SMILEYS_DIR, filename + ".gif")
    if not os.path.exists(path):
        return [], []
    if not TRAY_AVAILABLE:
        return [], []
    try:
        from PIL import Image, ImageSequence
        img = Image.open(path)
        frames, delays = [], []
        for frame in ImageSequence.Iterator(img):
            frames.append(frame.convert("RGBA"))
            d = frame.info.get("duration", 100)
            delays.append(max(int(d), 20))
        _GIF_FRAMES_CACHE[filename] = frames
        _GIF_DELAYS_CACHE[filename] = delays
        return frames, delays
    except Exception as e:
        print(f"Smileys: failed to load {path}: {e}")
        return [], []


class AnimatedSmiley:
    def __init__(self, text_widget: tk.Text, image_name: str, filename: str):
        self._widget   = text_widget
        self._img_name = image_name
        self._filename = filename
        self._frames, self._delays = _load_gif_frames(filename)
        self._photo_frames = []
        self._idx = 0
        self._job = None
        self._alive = True

        if not self._frames:
            return

        if TRAY_AVAILABLE:
            from PIL import ImageTk
            for f in self._frames:
                self._photo_frames.append(ImageTk.PhotoImage(f))

        self._schedule()

    def _schedule(self):
        if not self._alive or not self._photo_frames:
            return
        try:
            if not self._widget.winfo_exists():
                self._alive = False
                return
        except Exception:
            self._alive = False
            return
        delay = self._delays[self._idx] if self._idx < len(self._delays) else 100
        self._job = self._widget.after(delay, self._tick)

    def _tick(self):
        if not self._alive:
            return
        try:
            if not self._widget.winfo_exists():
                self._alive = False
                return
            self._idx = (self._idx + 1) % len(self._photo_frames)
            self._widget.image_configure(self._img_name, image=self._photo_frames[self._idx])
            self._schedule()
        except Exception:
            self._alive = False

    def stop(self):
        self._alive = False
        if self._job:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass


def parse_smileys(text: str) -> List[Tuple[str, str]]:
    result = []
    last = 0
    for m in _SMILEY_RE.finditer(text):
        s, e = m.start(), m.end()
        if s > last:
            result.append(("text", text[last:s]))
        code = m.group(0)
        result.append(("smiley", _CODE_TO_FILE[code]))
        last = e
    if last < len(text):
        result.append(("text", text[last:]))
    return result
