"""
resources.py — вспомогательные функции для работы с ресурсами:
  - поиск файлов рядом с .exe / скриптом
  - загрузка/кэширование спрайтов иконок (статус, xStatus)
  - воспроизведение звуков
  - флаг доступности pystray/Pillow
"""
import os
import sys
import threading
from typing import Dict, Optional

# ── Поиск ресурсов ───────────────────────────────────────────────────────────
def get_resource_path(relative_path: str) -> str:
    """Универсальный поиск ресурсов:
    1. Рядом с .exe (внешние файлы, приоритет)
    2. Во временной папке _MEIPASS (встроенные через --add-data)
    3. Рядом со скриптом (обычный запуск)
    """
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        exe_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(exe_path):
            return exe_path
        return os.path.join(sys._MEIPASS, relative_path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, relative_path)

# ── Попытка импорта библиотек для трея ───────────────────────────────────────
TRAY_AVAILABLE = False
try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk, ImageSequence
    TRAY_AVAILABLE = True
except ImportError:
    print("⚠ pystray или Pillow не найдены. Сворачивание в трей будет отключено.")
    print("   Установите: pip install pystray Pillow")

# ── xStatus иконки (спрайт xstatus.png) ──────────────────────────────────────
XSTATUS_ICON_W = 16
XSTATUS_ICON_H = 16

_XSTATUS_PHOTO_CACHE: Dict[int, object] = {}
_XSTATUS_SPRITE: Optional[object] = None

def _load_xstatus_sprite():
    global _XSTATUS_SPRITE
    if _XSTATUS_SPRITE is not None:
        return _XSTATUS_SPRITE
    if not TRAY_AVAILABLE:
        return None
    path = get_resource_path(os.path.join("icons", "xstatus.png"))
    if not os.path.exists(path):
        return None
    try:
        _XSTATUS_SPRITE = Image.open(path).convert("RGBA")
    except Exception as e:
        print(f"xStatus: не удалось загрузить спрайт: {e}")
    return _XSTATUS_SPRITE

def get_xstatus_photo(index: int) -> Optional[object]:
    """
    Возвращает PhotoImage для xStatus с заданным индексом из XSTATUS_TABLE.
    index=-1 → пустой статус (предпоследняя иконка).
    index=-2 → неизвестный (последняя иконка).
    Кэширует результат.
    """
    if not TRAY_AVAILABLE:
        return None
    sprite = _load_xstatus_sprite()
    if sprite is None:
        return None
    total = sprite.width // XSTATUS_ICON_W
    if index < 0:
        index = total + index
    if index < 0 or index >= total:
        return None
    if index in _XSTATUS_PHOTO_CACHE:
        return _XSTATUS_PHOTO_CACHE[index]
    x0 = index * XSTATUS_ICON_W
    icon = sprite.crop((x0, 0, x0 + XSTATUS_ICON_W, XSTATUS_ICON_H))
    photo = ImageTk.PhotoImage(icon)
    _XSTATUS_PHOTO_CACHE[index] = photo
    return photo

def get_xstatus_index_by_name(name: str) -> int:
    """Возвращает индекс xStatus по имени из XSTATUS_TABLE (или -1 если не найден)."""
    try:
        from icq_core import XSTATUS_TABLE
        for i, (_, n) in enumerate(XSTATUS_TABLE):
            if n == name:
                return i
    except Exception:
        pass
    return -1

# ── Иконки статусов (спрайт icons.png) ───────────────────────────────────────
STATUS_ICON_W = 16
STATUS_ICON_H = 16

_STATUS_SPRITE_INDEX: dict = {}

def _init_status_sprite_index():
    try:
        from icq_core import Status as _S
        _STATUS_SPRITE_INDEX[_S.AWAY]    = 0
        _STATUS_SPRITE_INDEX[_S.FREE]    = 1
        _STATUS_SPRITE_INDEX[_S.DND]     = 2
        _STATUS_SPRITE_INDEX[_S.NA]      = 4
        _STATUS_SPRITE_INDEX[_S.OFFLINE] = 6
        _STATUS_SPRITE_INDEX[_S.ONLINE]  = 7
    except Exception:
        pass

_STATUS_SPRITE: Optional[object] = None
_STATUS_PHOTO_CACHE: Dict[int, object] = {}

def _load_status_sprite():
    global _STATUS_SPRITE
    if _STATUS_SPRITE is not None:
        return _STATUS_SPRITE
    if not TRAY_AVAILABLE:
        return None
    path = get_resource_path(os.path.join("icons", "icons.png"))
    if not os.path.exists(path):
        return None
    try:
        _STATUS_SPRITE = Image.open(path).convert("RGBA")
    except Exception as e:
        print(f"Status icons: не удалось загрузить спрайт: {e}")
    return _STATUS_SPRITE

def get_status_photo(status) -> Optional[object]:
    """Возвращает PhotoImage иконки для данного статуса из icons.png."""
    if not TRAY_AVAILABLE:
        return None
    idx = _STATUS_SPRITE_INDEX.get(status)
    if idx is None:
        return None
    if idx in _STATUS_PHOTO_CACHE:
        return _STATUS_PHOTO_CACHE[idx]
    sprite = _load_status_sprite()
    if sprite is None:
        return None
    x0 = idx * STATUS_ICON_W
    if x0 + STATUS_ICON_W > sprite.width:
        return None
    icon = sprite.crop((x0, 0, x0 + STATUS_ICON_W, STATUS_ICON_H))
    photo = ImageTk.PhotoImage(icon)
    _STATUS_PHOTO_CACHE[idx] = photo
    return photo

def _create_simple_icon() -> Optional[object]:
    """Создаёт простую иконку для трея без внешних файлов."""
    if not TRAY_AVAILABLE:
        return None
    try:
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 28, 28], fill="#008000")
        draw.ellipse([10, 10, 22, 22], fill="#00cc00")
        return img
    except Exception:
        return None

# ── Звуки ─────────────────────────────────────────────────────────────────────
def _play_sound_file(wav_name: str):
    """Воспроизводит WAV-файл из папки sounds, кросс-платформенно."""
    try:
        wav_path = get_resource_path(os.path.join("sounds", wav_name))
        if sys.platform == "win32":
            import winsound
            if os.path.exists(wav_path):
                winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif sys.platform == "darwin":
            if os.path.exists(wav_path):
                os.system(f"afplay '{wav_path}' &")
            else:
                os.system("afplay /System/Library/Sounds/Tink.aiff &")
        else:
            if os.path.exists(wav_path):
                ret = os.system(f"paplay '{wav_path}' > /dev/null 2>&1")
                if ret != 0:
                    os.system(f"aplay '{wav_path}' > /dev/null 2>&1")
            else:
                ret = os.system("paplay /usr/share/sounds/freedesktop/stereo/message.oga > /dev/null 2>&1")
                if ret != 0:
                    print("\a", end="", flush=True)
    except Exception:
        pass

def _play_msg_sound():
    threading.Thread(target=_play_sound_file, args=("sndMsg.wav",), daemon=True).start()

def _play_online_sound():
    threading.Thread(target=_play_sound_file, args=("sndGlobal.wav",), daemon=True).start()

def _play_error_sound():
    threading.Thread(target=_play_sound_file, args=("sndSrvMsg.wav",), daemon=True).start()
