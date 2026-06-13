"""
main_window.py — MainWindow: главное окно приложения.
Содержит список контактов, трей, подключение к серверу и все колбэки.
"""
import asyncio
import queue as _queue
import threading
import logging
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Dict, Optional

from icq_core import (
    ICQClient, Status, Contact, Group, Message,
    UserInfo, SearchResult, XSTATUS_TABLE, AuthError,
)

from config import (
    load_config, save_config, load_font_config,
    set_loop, get_loop,
    STRANGERS_GROUP_ID, STRANGERS_GROUP_NAME,
    load_strangers, save_strangers,
    _cf, _uf,
)
from theme import (
    PALETTE, STATUS_COLORS, STATUS_ICONS, STATUS_LABELS,
    schedule_in_tk, place_near_parent,
)
from resources import (
    TRAY_AVAILABLE,
    get_status_photo, get_xstatus_photo, get_xstatus_index_by_name,
    _create_simple_icon, _load_status_sprite,
    _init_status_sprite_index, _STATUS_SPRITE_INDEX,
    STATUS_ICON_W, STATUS_ICON_H,
    XSTATUS_ICON_W, XSTATUS_ICON_H,
    _play_msg_sound, _play_online_sound, _play_error_sound,
)
from chat_window import ChatWindow
from dialogs import (
    LoginDialog, StatusDialog, UserInfoDialog,
    SearchDialog, AuthRequestDialog, AuthReplyNotification,
    _tk_queue, _schedule,
)
from notifications import DesktopNotification, ConnectionLostNotification

log = logging.getLogger("icq_ui")

if TRAY_AVAILABLE:
    import pystray
    from PIL import Image


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ICQ")
        self.geometry("280x600")
        self.minsize(220, 360)
        self.configure(bg=PALETTE["bg_main"])

        cfg = load_config()
        main_geom = cfg.get("main_window_geometry", "")
        if main_geom:
            try:
                self.geometry(main_geom)
            except Exception:
                pass
        self.bind("<Configure>", self._save_main_geometry)

        self._client: Optional[ICQClient] = None
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._chat_win: Optional[ChatWindow] = None
        self._my_status     = Status.ONLINE
        self._my_status_msg = ""
        self._my_nick       = ""
        self._unread_map:   Dict[str, int]  = {}
        self._typing_map:   Dict[str, bool] = {}
        self._session_id:   int  = 0
        self._roster_loaded: bool = False
        self._my_info_win     = None
        self._search_win      = None
        self._status_dlg_win  = None
        self._manage_grp_win  = None
        self._settings_win    = None
        self._add_contact_win = None
        self._pending_info_win: Dict[str, UserInfoDialog] = {}
        self._active_notifications: Dict[str, DesktopNotification] = {}
        self._conn_notif: Optional[ConnectionLostNotification] = None
        self._strangers: Dict[str, object] = {}

        self._group_items:   Dict[int, str] = {}
        self._contact_items: Dict[str, str] = {}
        self._build_ui()
        # Читаем _tk_queue через поллинг (event_generate ненадёжен в Python 3.14)
        self._poll_tk_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self._tray_icon = None
        self._init_tray()
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self._show_login()

    # ── Трей ──────────────────────────────────────────────────────────────────
    def _update_tray_icon(self):
        if not self._tray_icon or not TRAY_AVAILABLE:
            return
        idx    = _STATUS_SPRITE_INDEX.get(self._my_status)
        sprite = _load_status_sprite()
        if sprite is not None and idx is not None:
            x0       = idx * STATUS_ICON_W
            icon_16  = sprite.crop((x0, 0, x0 + STATUS_ICON_W, STATUS_ICON_H))
            tray_img = icon_16.resize((32, 32), Image.NEAREST)
        else:
            tray_img = _create_simple_icon()
        if tray_img:
            try:
                self._tray_icon.icon = tray_img
            except Exception:
                pass

    def _init_tray(self):
        if not TRAY_AVAILABLE:
            return
        try:
            icon_img = _create_simple_icon()
            if icon_img is None:
                return
            menu = pystray.Menu(
                pystray.MenuItem("Открыть ICQ",
                                 lambda: _schedule(self, self._restore_from_tray), default=True),
                pystray.MenuItem("Выйти",
                                 lambda: _schedule(self, self._exit_app))
            )
            self._tray_icon = pystray.Icon("icq_client", icon_img, "ICQ Client", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
            self.after(500, self._update_tray_icon)
        except Exception as e:
            print(f"⚠ Не удалось инициализировать трей: {e}")

    def _on_window_close(self):
        if self._tray_icon:
            self.withdraw()
        else:
            self.destroy()

    def _restore_from_tray(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _exit_app(self):
        if self._tray_icon:
            self._tray_icon.stop()
        self.quit()
        self.destroy()

    # ── Построение UI ─────────────────────────────────────────────────────────
    def _build_ui(self):
        status_frame = tk.Frame(self, bg=PALETTE["status_bar_bg"], pady=1)
        status_frame.pack(fill="x", side="bottom")

        self._status_ico_lbl = tk.Label(status_frame, bg=PALETTE["status_bar_bg"],
                                        image="", bd=0, cursor="hand2")
        self._status_ico_lbl._status_photo = None
        self._status_ico_lbl.pack(side="left", padx=(4, 1))
        self._status_ico_lbl.bind("<Button-1>", lambda e: self._change_status())

        self._statusbar_xs_lbl = tk.Label(status_frame, bg=PALETTE["status_bar_bg"],
                                          image="", bd=0, width=0, cursor="hand2")
        self._statusbar_xs_lbl._xstatus_photo = None
        self._statusbar_xs_lbl.bind("<Button-1>", lambda e: self._change_status())
        self._statusbar_xs_lbl.pack(side="left", padx=(1, 2))

        self._status_lbl = tk.Label(status_frame, text="Не в сети", font=_uf(delta=-1),
                                    bg=PALETTE["status_bar_bg"], fg=PALETTE["fg_offline"],
                                    cursor="hand2")
        self._status_lbl.pack(side="left", padx=(0, 4))
        self._status_lbl.bind("<Button-1>", lambda e: self._change_status())
        tk.Button(status_frame, text="☺", bg=PALETTE["status_bar_bg"], relief="flat",
                  font=_uf(), cursor="hand2", bd=0,
                  command=self._on_self_info).pack(side="right", padx=2)

        toolbar = tk.Frame(self, bg=PALETTE["toolbar_bg"], pady=1)
        toolbar.pack(fill="x", side="top")
        for ico, cmd, fnt in [
            ("☘", self._on_self_info,   _uf()),
            ("🔍", self._search_contact, ("Segoe UI Symbol", _uf()[1])),
            ("⁂", self._manage_groups,  _uf()),
            ("⚙", self._settings,       _uf()),
        ]:
            tk.Button(toolbar, text=ico, font=fnt, bg=PALETTE["toolbar_bg"],
                      fg=PALETTE["accent"], relief="flat", bd=0,
                      cursor="hand2", command=cmd).pack(side="left", padx=1)
        tk.Frame(self, height=1, bg=PALETTE["border"]).pack(fill="x")

        list_frame = tk.Frame(self, bg=PALETTE["bg_list"])
        list_frame.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(list_frame, bg=PALETTE["bg_list"],
                                 highlightthickness=0, bd=0)
        self._vsb = tk.Scrollbar(list_frame, orient="vertical",
                                 command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner = tk.Frame(self._canvas, bg=PALETTE["bg_list"])
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._inner.bind("<MouseWheel>", self._on_mousewheel)

        self._group_frames:   Dict[int, tk.Frame]  = {}
        self._group_labels:   Dict[int, tk.Label]  = {}
        self._group_lists:    Dict[int, tk.Frame]  = {}
        self._group_open:     Dict[int, bool]      = {}
        self._contact_rows:   Dict[str, tk.Frame]  = {}
        self._contact_ico:    Dict[str, tk.Label]  = {}
        self._contact_namelbl: Dict[str, tk.Label] = {}
        self._contact_unread: Dict[str, tk.Label]  = {}
        self._contact_xsico:  Dict[str, tk.Label]  = {}
        self._contact_authlbl: Dict[str, tk.Label] = {}  # ❗ — ожидание авторизации

    def _poll_tk_queue(self):
        """Каждые 50 мс читает глобальную _tk_queue в главном потоке.
        Заменяет event_generate("<<_TkCall>>"), которое ненадёжно в Python 3.14."""
        try:
            while True:
                func = _tk_queue.get_nowait()
                func()
        except _queue.Empty:
            pass
        except Exception:
            pass
        self.after(50, self._poll_tk_queue)

    def _on_inner_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _save_main_geometry(self, event):
        if event.widget is self:
            try:
                c = load_config()
                c["main_window_geometry"] = self.geometry()
                save_config(c)
            except Exception:
                pass

    # ── Логин / подключение ────────────────────────────────────────────────────
    def _show_login(self):
        cfg = load_config()
        if cfg.get("auto_connect") and cfg.get("uin") and cfg.get("password"):
            srv  = cfg.get("server", "195.66.114.37:5190")
            host, port = srv, 5190
            if ":" in srv:
                parts = srv.rsplit(":", 1)
                host  = parts[0]
                try: port = int(parts[1])
                except ValueError: pass
            self._connect(cfg["uin"], cfg["password"], host, port)
            return
        dlg = LoginDialog(self, cfg)
        self.wait_window(dlg)
        if dlg.result:
            uin, pwd, host, port = dlg.result
            self._connect(uin, pwd, host, port)
        else:
            self._status_lbl.configure(text="Не в сети", fg=PALETTE["fg_offline"])

    def _connect(self, uin: str, password: str, host: str, port: int):
        # Уничтожаем старое окно чата — оно привязано к старому клиенту/аккаунту,
        # поэтому при смене аккаунта история должна открываться заново с новым UIN.
        if self._chat_win is not None:
            try:
                if self._chat_win.winfo_exists():
                    self._chat_win.destroy()
            except Exception:
                pass
            self._chat_win = None

        if self._client is not None:
            try:
                self._client._stop_requested = True
                self._client._running = False
            except Exception:
                pass
            old_writer = getattr(self._client, "_writer", None)
            if old_writer:
                try: old_writer.close()
                except Exception: pass
        self._client = None

        old_loop   = self._loop
        self._loop = None

        self._session_id   += 1
        self._roster_loaded = False
        _sid = self._session_id

        self._clear_contact_list()

        self.title(f"{uin}")
        self._my_nick = ""
        if self._my_status == Status.OFFLINE:
            self._my_status = Status.ONLINE
        self._client = ICQClient(uin, password, host, port)

        def _guard(fn):
            def wrapper(*args):
                if self._session_id == _sid:
                    fn(*args)
            return wrapper

        def _guard_error(fn):
            fired = [False]
            def wrapper(exc):
                if self._session_id != _sid:
                    return
                if isinstance(exc, AuthError):
                    if fired[0]:
                        return
                    fired[0] = True
                fn(exc)
            return wrapper

        self._client.on_connected       = _guard(self._cb_connected)
        self._client.on_disconnected    = _guard(self._cb_disconnected)
        self._client.on_reconnecting    = _guard(self._cb_reconnecting)
        self._client.on_roster          = _guard(self._cb_roster)
        self._client.on_contact_online  = _guard(self._cb_contact_online)
        self._client.on_contact_offline = _guard(self._cb_contact_offline)
        self._client.on_contact_status  = _guard(self._cb_contact_status)
        self._client.on_message         = _guard(self._cb_message)
        self._client.on_typing          = _guard(self._cb_typing)
        self._client.on_error           = _guard_error(self._cb_error)
        self._client.on_xstatus_updated = _guard(self._cb_xstatus_updated)
        self._client.on_my_info         = _guard(self._cb_my_info)
        self._client.on_user_info       = _guard(self._cb_user_info)
        self._client.on_search_result   = _guard(self._cb_search_result)
        self._client.on_search_done     = _guard(self._cb_search_done)
        self._client.on_offline_message = _guard(self._cb_offline_message)
        self._client.on_auth_request    = _guard(self._cb_auth_request)
        self._client.on_auth_reply      = _guard(self._cb_auth_reply)
        self._client.on_you_were_added  = _guard(self._cb_you_were_added)

        self._loop = asyncio.new_event_loop()
        set_loop(self._loop)
        old_thread = getattr(self, "_thread", None)
        self._thread = threading.Thread(
            target=self._run_loop, args=(old_thread, self._loop), daemon=True)
        self._thread.start()
        self._status_lbl.configure(text="Подключение...")

    def _run_loop(self, prev_thread=None, my_loop=None):
        if prev_thread and prev_thread.is_alive():
            prev_thread.join(timeout=3.0)
        if my_loop is not self._loop:
            try: my_loop.close()
            except Exception: pass
            return
        asyncio.set_event_loop(my_loop)
        try:
            my_loop.run_until_complete(self._async_run())
        except RuntimeError as e:
            log.debug(f"_run_loop finished: {e}")
        except Exception as e:
            log.error(f"_run_loop unexpected error: {e}", exc_info=True)
        finally:
            try: my_loop.close()
            except Exception: pass

    async def _async_run(self):
        desired = self._my_status if self._my_status != Status.OFFLINE else Status.ONLINE
        await self._client.set_status(desired, self._my_status_msg)
        cfg      = load_config()
        xs_name  = cfg.get("xstatus_name", "")
        xs_title = cfg.get("xstatus_title", "")
        xs_desc  = cfg.get("xstatus_desc", "")
        if xs_name:
            await self._client.set_xstatus(xs_name, xs_title, xs_desc)
        await self._client.run()

    # ── Колбэки из ядра (вызываются из фонового потока) ──────────────────────
    def _cb_connected(self):
        asyncio.get_event_loop().create_task(self._client.request_my_info())
        schedule_in_tk(self, self._on_connected)
    def _cb_disconnected(self):    schedule_in_tk(self, self._on_disconnected)
    def _cb_reconnecting(self):    schedule_in_tk(self, self._on_reconnecting)
    def _cb_roster(self, g, c):    schedule_in_tk(self, self._on_roster, g, c)
    def _cb_contact_online(self, c):
        schedule_in_tk(self, self._on_contact_online, c)
        schedule_in_tk(self, self._on_contact_update, c)
    def _cb_contact_offline(self, c): schedule_in_tk(self, self._on_contact_update, c)
    def _cb_contact_status(self, c):  schedule_in_tk(self, self._on_contact_update, c)
    def _cb_message(self, msg):       schedule_in_tk(self, self._on_message, msg)
    def _cb_typing(self, u, t):       schedule_in_tk(self, self._on_typing, u, t)
    def _cb_error(self, exc):         schedule_in_tk(self, self._on_error, exc)
    def _cb_xstatus_updated(self, c): schedule_in_tk(self, self._on_xstatus_updated, c)
    def _cb_my_info(self, info):      schedule_in_tk(self, self._on_my_info, info)
    def _cb_user_info(self, info):    schedule_in_tk(self, self._on_user_info_received, info)
    def _cb_search_result(self, r):   schedule_in_tk(self, self._on_search_result, r)
    def _cb_search_done(self, rs):    schedule_in_tk(self, self._on_search_done, rs)
    def _cb_offline_message(self, msg): schedule_in_tk(self, self._on_offline_message, msg)
    def _cb_auth_request(self, uin, message):
        schedule_in_tk(self, self._on_auth_request, uin, message)
    def _cb_auth_reply(self, uin, granted, message):
        schedule_in_tk(self, self._on_auth_reply, uin, granted, message)
    def _cb_you_were_added(self, uin):
        schedule_in_tk(self, self._on_you_were_added, uin)

    # ── Незнакомцы ────────────────────────────────────────────────────────────
    def _make_stranger_contact(self, uin: str, name: str = "") -> object:
        return Contact(uin=uin, name=name or uin,
                       group_id=STRANGERS_GROUP_ID, item_id=0)

    def _load_strangers_for_account(self):
        if not self._client: return
        my_uin = self._client.uin
        raw    = load_strangers(my_uin)
        self._strangers = {}
        for uin, info in raw.items():
            if self._client.contacts.get(uin):
                continue
            contact = self._make_stranger_contact(uin, info.get("name", uin))
            self._strangers[uin] = contact
        if self._strangers:
            self._ensure_strangers_group()
            for contact in self._strangers.values():
                if contact.uin not in self._contact_rows:
                    self._add_contact(contact)
            self._rebuild_group(STRANGERS_GROUP_ID)

    def _ensure_strangers_group(self):
        if STRANGERS_GROUP_ID not in self._group_frames:
            g = Group(group_id=STRANGERS_GROUP_ID, name=STRANGERS_GROUP_NAME)
            self._add_group(g)

    def _refresh_strangers_group_visibility(self):
        frame = self._group_frames.get(STRANGERS_GROUP_ID)
        if not frame or not frame.winfo_exists(): return
        if self._strangers:
            frame.pack(fill="x", pady=0, padx=0)
        else:
            frame.pack_forget()

    def _register_stranger(self, uin: str, name: str = "") -> object:
        if uin in self._strangers:
            return self._strangers[uin]
        contact = self._make_stranger_contact(uin, name)
        self._strangers[uin] = contact
        self._ensure_strangers_group()
        if uin not in self._contact_rows:
            self._add_contact(contact)
        self._rebuild_group(STRANGERS_GROUP_ID)
        self._refresh_strangers_group_visibility()
        if self._client:
            raw = load_strangers(self._client.uin)
            raw[uin] = {"uin": uin, "name": name or uin}
            save_strangers(self._client.uin, raw)
        if self._client and self._loop:
            if not hasattr(self, "_pending_nick_fetch"):
                self._pending_nick_fetch: Dict[str, bool] = {}
            self._pending_nick_fetch[uin] = True
            asyncio.run_coroutine_threadsafe(
                self._client.request_user_info(uin), self._loop)
        return contact

    def _remove_stranger(self, uin: str):
        self._strangers.pop(uin, None)
        if hasattr(self, "_pending_nick_fetch"):
            self._pending_nick_fetch.pop(uin, None)
        if self._client:
            raw = load_strangers(self._client.uin)
            raw.pop(uin, None)
            save_strangers(self._client.uin, raw)
        self._refresh_strangers_group_visibility()

    # ── Колбэки UI ────────────────────────────────────────────────────────────
    def _on_connected(self):
        if self._conn_notif:
            try: self._conn_notif.destroy()
            except Exception: pass
            self._conn_notif = None
        self._update_status_bar()
        self._update_main_title()
        if self._client and self._loop and self._my_status != Status.OFFLINE:
            asyncio.run_coroutine_threadsafe(
                self._client.set_status(self._my_status, self._my_status_msg), self._loop)
            cfg      = load_config()
            xs_name  = cfg.get("xstatus_name", "")
            xs_title = cfg.get("xstatus_title", "")
            xs_desc  = cfg.get("xstatus_desc", "")
            if xs_name:
                asyncio.run_coroutine_threadsafe(
                    self._client.set_xstatus(xs_name, xs_title, xs_desc), self._loop)

    def _on_reconnecting(self):
        self._status_lbl.configure(text="Переподключение...", fg="#cc6600")
        if self._client:
            for contact in self._client.contacts.values():
                contact.status      = Status.OFFLINE
                contact.xstatus     = ""
                contact.xstatus_msg = ""
                self._update_contact_row(contact)

    def _on_disconnected(self):
        if self._my_status != Status.OFFLINE:
            self._status_lbl.configure(text="Отключено", fg=PALETTE["fg_offline"])
        if self._client:
            for contact in self._client.contacts.values():
                contact.status      = Status.OFFLINE
                contact.xstatus     = ""
                contact.xstatus_msg = ""
                self._update_contact_row(contact)
        if not self._conn_notif and self._my_status != Status.OFFLINE:
            self._show_conn_error("Соединение потеряно. Нажмите чтобы переподключиться.")

    def _on_roster(self, groups: list, contacts: list):
        for g in groups: self._add_group(g)
        for c in contacts:
            if c.uin in self._contact_rows:
                # Контакт уже в списке — обновляем только значок pending_auth
                lbl = self._contact_authlbl.get(c.uin)
                if lbl and lbl.winfo_exists():
                    lbl.configure(text="❗" if getattr(c, "pending_auth", False) else "")
            else:
                self._add_contact(c)
        self._rebuild_list()
        self._load_strangers_for_account()
        self.after(2000, self._set_roster_loaded)

    def _set_roster_loaded(self):
        self._roster_loaded = True

    def _on_contact_online(self, contact):
        if self._roster_loaded and self._my_status in (Status.ONLINE, Status.FREE):
            _play_online_sound()

    def _on_contact_update(self, contact):
        self._update_contact_row(contact)
        cw = self._chat_win
        if cw and cw.winfo_exists() and cw.has_contact(contact.uin):
            cw.update_contact(contact)

    def _on_xstatus_updated(self, contact):
        self._on_contact_update(contact)

    def _on_my_info(self, info: UserInfo):
        nick    = info.nick or ""
        self._my_nick = nick
        uin_str = self._client.uin if self._client else ""
        title   = f"{nick} ({uin_str})" if nick else uin_str
        self.title(title)
        if hasattr(self, "_my_info_win") and self._my_info_win and self._my_info_win.winfo_exists():
            self._my_info_win.load_info(info)

    def _on_user_info_received(self, info: UserInfo):
        pending      = getattr(self, "_pending_nick_fetch", {})
        fetch_reason = pending.pop(info.uin, None)
        if fetch_reason:
            nick = info.nick or info.first_name or ""
            if nick:
                stranger = self._strangers.get(info.uin)
                if stranger and nick != stranger.name:
                    stranger.name = nick
                    lbl = self._contact_namelbl.get(info.uin)
                    if lbl and lbl.winfo_exists():
                        lbl.configure(text=nick)
                    if self._client:
                        raw = load_strangers(self._client.uin)
                        if info.uin in raw:
                            raw[info.uin]["name"] = nick
                            save_strangers(self._client.uin, raw)
                roster_contact = self._client.contacts.get(info.uin) if self._client else None
                if roster_contact and fetch_reason == "roster" and not roster_contact.name:
                    roster_contact.name = nick
                    self._update_contact_row(roster_contact)
        win = getattr(self, "_pending_info_win", {}).get(info.uin)
        if win and win.winfo_exists():
            win.load_info(info)

        pending_add = getattr(self, "_pending_add_fetch", {})
        if info.uin in pending_add:
            saved_nick = pending_add.pop(info.uin)
            resolved_nick = saved_nick or info.nick or info.first_name or ""
            self._add_contact_dialog(info.uin, resolved_nick, bool(info.auth_required))

    def _on_search_result(self, result: SearchResult):
        win = getattr(self, "_search_win", None)
        if win and win.winfo_exists():
            win.add_result(result)

    def _on_search_done(self, results: list):
        win = getattr(self, "_search_win", None)
        if win and win.winfo_exists():
            win.search_done(results)

    def _on_offline_message(self, msg: Message):
        sender  = msg.sender_uin
        contact = (self._client.contacts.get(sender) if self._client else None)
        if contact is None:
            contact = self._strangers.get(sender)
        if contact is None:
            contact = self._register_stranger(sender)
        cw = self._get_or_ensure_chat_win()
        if not cw.has_contact(sender):
            cw.open_contact_silent(contact)
        cw.append_message(sender, msg)

    def _on_auth_request(self, uin: str, message: str):
        if not self._client or not self._loop: return
        contact      = self._client.contacts.get(uin)
        display_name = contact.display_name if contact else uin
        key          = f"_auth_req_{uin}"
        existing     = getattr(self, key, None)
        if existing and existing.winfo_exists():
            existing.lift(); return
        dlg = AuthRequestDialog(self, uin, display_name, message)
        def on_reply(u, granted, reason):
            asyncio.run_coroutine_threadsafe(
                self._client.send_auth_reply(u, granted, reason), self._loop)
            word = "разрешена" if granted else "отклонена"
            self._status_lbl.configure(text=f"Авторизация {word}: {display_name}")
            self.after(4000, lambda: self._status_lbl.configure(
                text=self._client.my_nick or self._client.uin if self._client else ""))
        dlg.on_reply = on_reply
        setattr(self, key, dlg)
        dlg.protocol("WM_DELETE_WINDOW", lambda: (
            delattr(self, key) if hasattr(self, key) else None,
            dlg.destroy()
        ))

    def _on_auth_reply(self, uin: str, granted: bool, message: str):
        contact      = self._client.contacts.get(uin) if self._client else None
        display_name = contact.display_name if contact else uin
        AuthReplyNotification(self, uin, display_name, granted, message)
        if contact:
            # Обновить значок ❗ сразу
            lbl = self._contact_authlbl.get(uin)
            if lbl and lbl.winfo_exists():
                lbl.configure(text="" if granted else "❗")
        if granted and contact:
            # Принудительно перерисовать строку контакта
            contact.pending_auth = False
            self._update_contact_row(contact)
            self._on_contact_update(contact)

    def _on_you_were_added(self, uin: str):
        contact      = self._client.contacts.get(uin) if self._client else None
        display_name = contact.display_name if contact else uin
        snippet = f"{display_name} ({uin}) добавил вас в список"
        notif   = DesktopNotification(
            self, uin, "Вас добавили в список", snippet,
            callback=lambda u=uin, n=display_name: self._add_contact_fetch_and_dialog(u, n),
            auto_close=False
        )
        try:
            for widget in notif.winfo_children():
                for child in widget.winfo_children():
                    if isinstance(child, tk.Label) and "✉" in (child.cget("text") or ""):
                        child.configure(text=f"☺ {display_name} ({uin})")
                        break
        except Exception:
            pass
        self._active_notifications[uin] = notif
        notif.protocol("WM_DELETE_WINDOW",
                       lambda u=uin, n=notif: (
                           self._active_notifications.pop(u, None),
                           n.destroy()
                       ))
        if self._client and uin not in self._client.contacts:
            self._register_stranger(uin, display_name)

    def _on_message(self, msg: Message):
        sender  = msg.sender_uin
        contact = (self._client.contacts.get(sender) if self._client else None)
        if contact is None:
            contact = self._strangers.get(sender)
        if contact is None:
            contact = self._register_stranger(sender)
        cw = self._get_or_ensure_chat_win()
        if not cw.has_contact(sender):
            cw.open_contact_silent(contact)
        cw.append_message(sender, msg)
        if not msg.is_outgoing:
            if self._my_status in (Status.ONLINE, Status.FREE):
                _play_msg_sound()
            if self._my_status not in (Status.DND, Status.NA, Status.AWAY, Status.OFFLINE):
                chat_is_focused = (
                    cw.winfo_exists()
                    and cw.winfo_viewable()
                    and cw._active_uin == sender
                    and cw.focus_get() is not None
                )
                if not chat_is_focused:
                    prev = self._active_notifications.get(sender)
                    if prev:
                        try: prev.destroy()
                        except Exception: pass
                    snippet = msg.text[:50] + ("..." if len(msg.text) > 50 else "")
                    notif = DesktopNotification(
                        self, sender, contact.display_name, snippet,
                        lambda c=contact: self._open_chat(c)
                    )
                    self._active_notifications[sender] = notif
                    notif.protocol("WM_DELETE_WINDOW",
                                   lambda u=sender, n=notif: (
                                       self._active_notifications.pop(u, None),
                                       n.destroy()
                                   ))

    def _on_typing(self, uin: str, is_typing: bool):
        if is_typing:
            self._typing_map[uin] = True
        else:
            self._typing_map.pop(uin, None)
        cw = self._chat_win
        if cw and cw.winfo_exists():
            cw.show_typing(uin, is_typing)

    def _on_unread_message(self, uin: str):
        cw = self._chat_win
        n  = cw.get_unread(uin) if (cw and cw.winfo_exists()) else 1
        self._unread_map[uin] = n
        badge = self._contact_unread.get(uin)
        if badge and badge.winfo_exists():
            badge.configure(text=str(n), bg=PALETTE["unread_badge"], fg="#ffffff")
        contact = (self._client.contacts.get(uin) if self._client else None) \
                  or self._strangers.get(uin)
        if contact:
            self._rebuild_group(contact.group_id)
        self._update_main_title()

    def _on_unread_cleared(self, uin: str):
        self._unread_map[uin] = 0
        badge = self._contact_unread.get(uin)
        if badge and badge.winfo_exists():
            badge.configure(text="", bg=PALETTE["bg_list"], fg=PALETTE["bg_list"])
        contact = (self._client.contacts.get(uin) if self._client else None) \
                  or self._strangers.get(uin)
        if contact:
            self._rebuild_group(contact.group_id)
        self._update_main_title()

    def _on_error(self, exc):
        if isinstance(exc, AuthError):
            if getattr(self, "_auth_error_handling", False): return
            self._auth_error_handling = True
            self._status_lbl.configure(text="Ошибка входа", fg="#cc0000")
            messagebox.showerror("Ошибка авторизации",
                "Неверный UIN или пароль.\n\nПроверьте данные и попробуйте снова.",
                parent=self)
            self._auth_error_handling = False
            cfg = load_config()
            dlg = LoginDialog(self, cfg)
            self.wait_window(dlg)
            if dlg.result:
                uin, pwd, host, port = dlg.result
                self._connect(uin, pwd, host, port)
            return
        else:
            self._status_lbl.configure(text="Ошибка подключения", fg="#cc0000")
            _play_error_sound()
            msg = str(exc)
            if "Timeout" in msg or "timeout" in msg:
                text = "Нет ответа от сервера. Нажмите чтобы переподключиться."
            elif "другого клиента" in msg or "ch4" in msg.lower() or "сервер разорвал" in msg:
                text = "Сервер разорвал соединение. Нажмите чтобы переподключиться."
            elif "refused" in msg.lower() or "connect" in msg.lower():
                text = "Не удалось подключиться к серверу. Нажмите чтобы повторить."
            else:
                text = f"Обрыв связи: {msg[:60]}. Нажмите чтобы переподключиться."
            self._show_conn_error(text)

    # ── Список контактов ───────────────────────────────────────────────────────
    def _add_group(self, group):
        gid = group.group_id
        if gid in self._group_frames: return
        self._group_open[gid] = True
        frame = tk.Frame(self._inner, bg=PALETTE["bg_list"])
        frame.pack(fill="x", pady=0, padx=0)
        hdr = tk.Frame(frame, bg=PALETTE["bg_header"], pady=0)
        hdr.pack(fill="x")
        arrow_lbl = tk.Label(hdr, text="▼", font=_uf(delta=-2),
                             bg=PALETTE["bg_header"], fg=PALETTE["fg_group"], cursor="hand2")
        arrow_lbl.pack(side="left", padx=2)
        tk.Label(hdr, text="❋", font=_uf(delta=-1),
                 bg=PALETTE["bg_header"], fg="#cc6600").pack(side="left")
        grp_lbl = tk.Label(hdr, text=group.name, font=_uf(bold=False),
                           bg=PALETTE["bg_header"], fg=PALETTE["fg_group"],
                           cursor="hand2", anchor="w")
        grp_lbl.pack(side="left", fill="x", expand=True, padx=2)
        count_lbl = tk.Label(hdr, text="0/0", font=_uf(delta=-2),
                             bg=PALETTE["bg_header"], fg=PALETTE["fg_group"])
        count_lbl.pack(side="right", padx=3)
        clist = tk.Frame(frame, bg=PALETTE["bg_list"])
        clist.pack(fill="x")
        def toggle(e, gid=gid, arrow=arrow_lbl, clist=clist):
            self._group_open[gid] = not self._group_open[gid]
            if self._group_open[gid]: clist.pack(fill="x"); arrow.configure(text="▼")
            else: clist.pack_forget(); arrow.configure(text="►")
        for w in (hdr, grp_lbl, arrow_lbl): w.bind("<Button-1>", toggle)
        self._group_frames[gid]  = frame
        self._group_labels[gid]  = count_lbl
        self._group_lists[gid]   = clist

    def _add_contact(self, contact):
        if contact.uin in self._contact_rows: return
        gid = contact.group_id
        if gid not in self._group_lists:
            self._add_group(Group(group_id=gid, name=f"Группа {gid}"))
        clist = self._group_lists[gid]
        row   = tk.Frame(clist, bg=PALETTE["bg_list"], cursor="hand2")
        row.pack(fill="x", padx=1, pady=1)

        _st_photo = get_status_photo(contact.status)
        if _st_photo:
            status_ico = tk.Label(row, image=_st_photo, bg=PALETTE["bg_list"],
                                  width=STATUS_ICON_W, height=STATUS_ICON_H, bd=0)
            status_ico._status_photo = _st_photo
        else:
            status_ico = tk.Label(row, text=STATUS_ICONS.get(contact.status, "○"),
                                  font=_uf(), bg=PALETTE["bg_list"],
                                  fg=STATUS_COLORS.get(contact.status, "#808080"), width=2)
            status_ico._status_photo = None
        status_ico.pack(side="left", padx=(3, 1))

        xs_photo_lbl = tk.Label(row, bg=PALETTE["bg_list"], image="", bd=0, padx=0, pady=0)
        xs_photo_lbl.pack(side="left", padx=(0, 2))
        xs_photo_lbl._xstatus_photo = None

        auth_lbl = tk.Label(row, text="", font=_uf(delta=-1),
                            bg=PALETTE["bg_list"], fg="#cc0000", padx=0)
        auth_lbl.pack(side="left")
        if getattr(contact, "pending_auth", False):
            auth_lbl.configure(text="❗")

        name_lbl = tk.Label(row, text=contact.display_name, font=_uf(),
                            bg=PALETTE["bg_list"],
                            fg=PALETTE["fg_online"] if contact.is_online else PALETTE["fg_offline"],
                            anchor="w", cursor="hand2")
        name_lbl.pack(side="left", fill="x", expand=True)

        unread_lbl = tk.Label(row, text="", font=_uf(bold=True),
                              bg=PALETTE["bg_list"], fg=PALETTE["bg_list"], width=3)
        unread_lbl.pack(side="right", padx=(0, 2))

        uin_lbl = tk.Label(row, text=f"({contact.uin})", font=_uf(delta=-1),
                           bg=PALETTE["bg_list"], fg=PALETTE["msg_time"])
        uin_lbl.pack(side="right", padx=2)

        def on_click(e, c=contact):
            real = self._client.contacts.get(c.uin, c)
            self._open_chat(real)
        def on_hover_enter(e, r=row):
            r.configure(bg=PALETTE["select_bg"])
            for w in r.winfo_children():
                try: w.configure(bg=PALETTE["select_bg"])
                except: pass
            if unread_lbl.cget("text"): unread_lbl.configure(bg=PALETTE["unread_badge"])
        def on_hover_leave(e, r=row):
            r.configure(bg=PALETTE["bg_list"])
            for w in r.winfo_children():
                try: w.configure(bg=PALETTE["bg_list"])
                except: pass
            if unread_lbl.cget("text"): unread_lbl.configure(bg=PALETTE["unread_badge"])
        def on_right(e, c=contact): self._show_contact_menu(e, c)

        for widget in [row, status_ico, name_lbl, uin_lbl, unread_lbl, xs_photo_lbl]:
            widget.bind("<Button-1>",        on_click)
            widget.bind("<Double-Button-1>", on_click)
            widget.bind("<Button-3>",        on_right)
            widget.bind("<Enter>",           on_hover_enter)
            widget.bind("<Leave>",           on_hover_leave)

        self._contact_rows[contact.uin]    = row
        self._contact_ico[contact.uin]     = status_ico
        self._contact_namelbl[contact.uin] = name_lbl
        self._contact_unread[contact.uin]  = unread_lbl
        self._contact_xsico[contact.uin]   = xs_photo_lbl
        self._contact_authlbl[contact.uin] = auth_lbl

    def _update_contact_row(self, contact):
        row = self._contact_rows.get(contact.uin)
        if row is None or not row.winfo_exists():
            self._add_contact(contact); return
        ico    = self._contact_ico.get(contact.uin)
        name   = self._contact_namelbl.get(contact.uin)
        xs_ico = self._contact_xsico.get(contact.uin)
        if ico and ico.winfo_exists():
            _st_photo = get_status_photo(contact.status)
            if _st_photo:
                ico.configure(image=_st_photo, text="",
                              width=STATUS_ICON_W, height=STATUS_ICON_H,
                              fg=PALETTE["bg_list"])
                ico._status_photo = _st_photo
            else:
                ico.configure(image="", text=STATUS_ICONS.get(contact.status, "○"),
                              fg=STATUS_COLORS.get(contact.status, "#808080"), width=2)
                ico._status_photo = None
        if name and name.winfo_exists():
            name.configure(text=contact.display_name,
                           fg=PALETTE["fg_online"] if contact.is_online else PALETTE["fg_offline"])
        if xs_ico and xs_ico.winfo_exists():
            xs_name = getattr(contact, "xstatus", "")
            if xs_name:
                idx   = get_xstatus_index_by_name(xs_name)
                photo = get_xstatus_photo(idx) if idx >= 0 else None
                if photo:
                    xs_ico.configure(image=photo, width=XSTATUS_ICON_W, height=XSTATUS_ICON_H)
                    xs_ico._xstatus_photo = photo
                else:
                    xs_ico.configure(image="", width=0, height=0)
                    xs_ico._xstatus_photo = None
            else:
                xs_ico.configure(image="", width=0, height=0)
                xs_ico._xstatus_photo = None
        auth_lbl_w = self._contact_authlbl.get(contact.uin)
        if auth_lbl_w and auth_lbl_w.winfo_exists():
            auth_lbl_w.configure(text="❗" if getattr(contact, "pending_auth", False) else "")
        self._rebuild_group(contact.group_id)

    def _clear_contact_list(self):
        for frame in self._group_frames.values():
            try: frame.destroy()
            except Exception: pass
        self._group_frames.clear()
        self._group_labels.clear()
        self._group_lists.clear()
        self._group_open.clear()
        self._contact_rows.clear()
        self._contact_ico.clear()
        self._contact_namelbl.clear()
        self._contact_authlbl.clear()
        self._contact_unread.clear()
        self._contact_xsico.clear()
        self._unread_map.clear()
        self._typing_map.clear()
        self._strangers.clear()

    def _rebuild_group(self, group_id: int):
        clist = self._group_lists.get(group_id)
        if not clist: return
        cw = self._chat_win
        if group_id == STRANGERS_GROUP_ID:
            contacts_in_group = sorted(
                self._strangers.values(),
                key=lambda c: ((cw.get_unread(c.uin) == 0) if (cw and cw.winfo_exists()) else True,
                               c.display_name.lower())
            )
        else:
            contacts_in_group = sorted(
                [c for c in self._client.contacts.values() if c.group_id == group_id],
                key=lambda c: ((cw.get_unread(c.uin) == 0) if (cw and cw.winfo_exists()) else True,
                               not c.is_online, c.display_name.lower())
            )
        for c in contacts_in_group:
            row = self._contact_rows.get(c.uin)
            if row and row.winfo_exists():
                row.pack_forget()
                row.pack(fill="x", padx=2, pady=0)
            badge = self._contact_unread.get(c.uin)
            if badge and badge.winfo_exists():
                n = self._unread_map.get(c.uin, 0)
                if n:
                    badge.configure(text=str(n), bg=PALETTE["unread_badge"], fg="#ffffff")
                else:
                    badge.configure(text="", bg=PALETTE["bg_list"], fg=PALETTE["bg_list"])
        count_lbl = self._group_labels.get(group_id)
        if count_lbl:
            online = sum(1 for c in contacts_in_group if c.is_online)
            count_lbl.configure(text=f"{online}/{len(contacts_in_group)}")

    def _rebuild_list(self):
        for gid in self._group_lists:
            self._rebuild_group(gid)

    def apply_ui_fonts(self):
        for lbl in self._contact_namelbl.values():
            try:
                if lbl.winfo_exists(): lbl.configure(font=_uf())
            except Exception: pass
        for lbl in self._contact_unread.values():
            try:
                if lbl.winfo_exists(): lbl.configure(font=_uf(bold=True))
            except Exception: pass
        for row in self._contact_rows.values():
            try:
                if not row.winfo_exists(): continue
                for w in row.winfo_children():
                    if isinstance(w, tk.Label):
                        t = w.cget("text")
                        if isinstance(t, str) and t.startswith("(") and t.endswith(")"):
                            w.configure(font=_uf(delta=-1))
            except Exception: pass
        for frame in self._group_frames.values():
            try:
                if not frame.winfo_exists(): continue
                for hdr in frame.winfo_children():
                    if not isinstance(hdr, tk.Frame): continue
                    for w in hdr.winfo_children():
                        if not isinstance(w, tk.Label): continue
                        t = w.cget("text")
                        if t in ("▼", "►"):
                            w.configure(font=_uf(delta=-2))
                        elif t == "❋":
                            w.configure(font=_uf(delta=-1))
                        elif t not in ("", "▼", "►", "❋") and "/" in str(t):
                            w.configure(font=_uf(delta=-2))
                        else:
                            try:
                                f = w.cget("font")
                                if "bold" in str(f):
                                    w.configure(font=_uf(bold=True))
                            except Exception: pass
            except Exception: pass
        for lbl in self._group_labels.values():
            try:
                if lbl.winfo_exists(): lbl.configure(font=_uf(delta=-2))
            except Exception: pass
        try:
            if self._status_lbl.winfo_exists():
                self._status_lbl.configure(font=_uf(delta=-1))
        except Exception: pass

    # ── Чат ───────────────────────────────────────────────────────────────────
    def _get_or_ensure_chat_win(self) -> ChatWindow:
        if self._chat_win is None or not self._chat_win.winfo_exists():
            self._chat_win = ChatWindow(self, self._client)
            self._chat_win.withdraw()
            for uin, typing in self._typing_map.items():
                if typing:
                    self._chat_win.show_typing(uin, True)
        return self._chat_win

    def _open_chat(self, contact):
        cw = self._get_or_ensure_chat_win()
        if not cw.has_contact(contact.uin): cw.open_contact(contact)
        else: cw._switch_tab(contact.uin)
        cw.deiconify(); cw.lift()
        if getattr(contact, "is_online", False) and self._client and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._client.request_xstatus(contact.uin), self._loop)

    # ── Контекстное меню контакта ─────────────────────────────────────────────
    def _send_auth_request_dialog(self, contact):
        """Диалог повторного запроса авторизации для pending_auth контакта."""
        if not self._client or not self._loop: return
        win = tk.Toplevel(self)
        win.title("Запрос авторизации")
        win.configure(bg=PALETTE["bg_main"])
        win.resizable(False, False)
        win.grab_set()
        tk.Label(win, text=f"🔑 Запрос авторизации: {contact.display_name}",
                 font=("Segoe UI Symbol", 10, "bold"),
                 bg=PALETTE["title_bar"], fg="white").pack(fill="x")
        body = tk.Frame(win, bg=PALETTE["bg_main"], padx=16, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Сообщение (необязательно):",
                 font=("Segoe UI Symbol", 8), bg=PALETTE["bg_main"]).pack(anchor="w")
        msg_var = tk.StringVar()
        tk.Entry(body, textvariable=msg_var, font=("Segoe UI Symbol", 9),
                 width=36, relief="groove", bd=2).pack(pady=(2, 6), fill="x")
        status_lbl = tk.Label(body, text="", font=("Segoe UI Symbol", 8),
                              bg=PALETTE["bg_main"], fg="#0055aa")
        status_lbl.pack(anchor="w")
        def do_send():
            msg = msg_var.get().strip()
            status_lbl.configure(text="Отправляю...", fg="#0055aa")
            win.update()
            asyncio.run_coroutine_threadsafe(
                self._client.send_auth_request(contact.uin, msg), self._loop)
            status_lbl.configure(text="✔ Запрос отправлен", fg="#006600")
            win.after(900, win.destroy)
        btn_f = tk.Frame(win, bg=PALETTE["bg_main"])
        btn_f.pack(pady=6)
        tk.Button(btn_f, text="Отправить", font=("Segoe UI Symbol", 9, "bold"),
                  bg="#3a7abf", fg="white", relief="groove", padx=12,
                  cursor="hand2", command=do_send).pack(side="left", padx=6)
        tk.Button(btn_f, text="Отмена", font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                  relief="groove", padx=10, cursor="hand2",
                  command=win.destroy).pack(side="left")
        place_near_parent(win, self)

    def _show_contact_menu(self, event, contact):
        # Всегда берём актуальный объект из roster — локальная копия может устареть
        # (например, pending_auth мог измениться после добавления или подтверждения)
        live = (self._client and self._client.contacts.get(contact.uin)) or contact
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=f"✉ Написать {live.display_name}",
                         command=lambda: self._open_chat(live))
        menu.add_separator()
        menu.add_command(label="ℹ Анкета контакта",
                         command=lambda: self._show_contact_info(live))
        menu.add_separator()
        in_roster   = self._client and live.uin in self._client.contacts
        is_stranger = live.uin in self._strangers
        if not in_roster:
            menu.add_command(label="➕ Добавить в список",
                             command=lambda: self._add_contact_fetch_and_dialog(
                                 live.uin,
                                 live.display_name if live.display_name != live.uin else ""))
        if in_roster and getattr(live, "pending_auth", False):
            menu.add_command(label="🔑 Повторить запрос авторизации",
                             command=lambda: self._send_auth_request_dialog(live))
        menu.add_command(label="✏ Переименовать",
                         command=lambda: self._rename_contact_dialog(live))
        if in_roster:
            menu.add_command(label="❑ Переместить в группу",
                             command=lambda: self._move_contact_dialog(live))
        menu.add_command(label="✖ Удалить из списка",
                         command=lambda: self._remove_contact_confirm(live))
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()

    def _show_contact_info(self, contact):
        if not self._client: return
        if not hasattr(self, "_pending_info_win"):
            self._pending_info_win = {}
        existing = self._pending_info_win.get(contact.uin)
        if existing and existing.winfo_exists():
            existing.deiconify(); existing.lift(); existing.focus_force(); return
        win = UserInfoDialog(self, contact.uin, contact.display_name, editable=False)
        self._pending_info_win[contact.uin] = win
        win.set_status("⊙ Загружаю анкету с сервера...", color="#0055aa")
        win.protocol("WM_DELETE_WINDOW",
                     lambda: [win.destroy(),
                              self._pending_info_win.pop(contact.uin, None)])
        win.deiconify(); win.lift()
        asyncio.run_coroutine_threadsafe(
            self._client.request_user_info(contact.uin), self._loop)

    def _add_contact_fetch_and_dialog(self, uin: str, nick: str = ""):
        """Запрашивает auth_required из анкеты, затем открывает диалог добавления (как через поиск)."""
        if not self._client: return
        if not hasattr(self, "_pending_add_fetch"):
            self._pending_add_fetch = {}
        self._pending_add_fetch[uin] = nick
        asyncio.run_coroutine_threadsafe(
            self._client.request_user_info(uin), self._loop)

    def _add_contact_dialog(self, prefill_uin: str = "", prefill_nick: str = "",
                            prefill_auth_req: bool = False):
        if not self._client: return
        if not prefill_uin and self._add_contact_win and self._add_contact_win.winfo_exists():
            self._add_contact_win.lift(); self._add_contact_win.focus_force(); return
        if prefill_uin and not prefill_nick:
            stranger = self._strangers.get(prefill_uin)
            if stranger and stranger.name and stranger.name != prefill_uin:
                prefill_nick = stranger.name

        win = tk.Toplevel(self)
        self._add_contact_win = win
        win.title("Добавить контакт")
        win.configure(bg=PALETTE["bg_main"])
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="➕ Добавить контакт", font=("Segoe UI Symbol", 10, "bold"),
                 bg=PALETTE["title_bar"], fg="white").pack(fill="x")
        body = tk.Frame(win, bg=PALETTE["bg_main"], padx=16, pady=8)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        tk.Label(body, text="UIN:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"], anchor="e").grid(row=0, column=0, sticky="e", pady=4)
        uin_var = tk.StringVar(value=prefill_uin)
        tk.Entry(body, textvariable=uin_var, font=("Segoe UI Symbol", 10),
                 width=20, relief="groove", bd=2).grid(row=0, column=1, padx=6, sticky="ew")

        tk.Label(body, text="Псевдоним:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"], anchor="e").grid(row=1, column=0, sticky="e", pady=4)
        nick_var = tk.StringVar(value=prefill_nick)
        tk.Entry(body, textvariable=nick_var, font=("Segoe UI Symbol", 10),
                 width=20, relief="groove", bd=2).grid(row=1, column=1, padx=6, sticky="ew")

        tk.Label(body, text="Группа:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"], anchor="e").grid(row=2, column=0, sticky="e", pady=4)
        groups_sorted = sorted(self._client.groups.values(), key=lambda g: g.name.lower())
        group_labels  = [f"{g.name}" for g in groups_sorted] or ["General"]
        group_ids     = [g.group_id  for g in groups_sorted] or [0]
        group_var     = tk.StringVar(value=group_labels[0])
        group_combo   = ttk.Combobox(body, textvariable=group_var, values=group_labels,
                                     width=19, state="readonly")
        group_combo.grid(row=2, column=1, padx=6, sticky="ew")
        group_combo.current(0)

        if prefill_auth_req:
            tk.Label(body, text="❗ Требуется авторизация — запрос будет отправлен автоматически",
                     font=("Segoe UI Symbol", 7, "italic"), bg=PALETTE["bg_main"],
                     fg="#aa5500", wraplength=260, justify="left").grid(
                     row=3, column=0, columnspan=2, sticky="w", pady=(0, 2))
        status_lbl = tk.Label(body, text="", font=("Segoe UI Symbol", 8),
                              bg=PALETTE["bg_main"], fg="#006600")
        status_lbl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))

        def _get_selected_group_id() -> int:
            idx = group_combo.current()
            if idx < 0 or idx >= len(group_ids): return group_ids[0] if group_ids else 0
            return group_ids[idx]

        def do_add():
            uin  = uin_var.get().strip()
            nick = nick_var.get().strip()
            if not uin.isdigit():
                status_lbl.configure(text="⚠ UIN должен быть числом", fg="#cc0000"); return
            gid = _get_selected_group_id()
            status_lbl.configure(text="Добавляю...", fg="#0055aa")
            win.update()
            def task():
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.add_contact(uin, nick, group_id=gid,
                                             auth_required=prefill_auth_req), self._loop)
                try: ok = fut.result(timeout=15)
                except Exception as e: ok = False; log.error(f"add_contact error: {e}")
                def on_done():
                    # ok == True, "auth_required", или False
                    if ok == "auth_required":
                        # Контакт добавлен в SSI с pending_auth=True, ждёт авторизации
                        status_lbl.configure(
                            text="❗ Пользователь требует авторизацию.\nЗапрос отправлен, ожидайте подтверждения.",
                            fg="#cc6600")
                        contact = self._client.contacts.get(uin)
                        if contact:
                            if gid not in self._group_lists:
                                grp = self._client.groups.get(gid)
                                if grp is None:
                                    grp = Group(group_id=gid, name="General")
                                self._add_group(grp)
                            # Убираем из strangers — контакт уже в roster (pending)
                            if uin in self._strangers:
                                unread_count = self._unread_map.get(uin, 0)
                                self._remove_stranger(uin)
                                row = self._contact_rows.pop(uin, None)
                                if row and row.winfo_exists(): row.destroy()
                                self._contact_ico.pop(uin, None)
                                self._contact_namelbl.pop(uin, None)
                                self._contact_unread.pop(uin, None)
                                self._rebuild_group(STRANGERS_GROUP_ID)
                                self._unread_map[uin] = unread_count
                            if uin not in self._contact_rows:
                                self._add_contact(contact)
                            else:
                                lbl = self._contact_authlbl.get(uin)
                                if lbl and lbl.winfo_exists():
                                    lbl.configure(text="❗")
                            self._rebuild_group(gid)
                            badge = self._contact_unread.get(uin)
                            unread_count = self._unread_map.get(uin, 0)
                            if badge and badge.winfo_exists() and unread_count:
                                badge.configure(text=str(unread_count),
                                                bg=PALETTE["unread_badge"], fg="#ffffff")
                        self._update_main_title()
                        win.after(3000, win.destroy)
                    elif ok:
                        status_lbl.configure(text="✔ Добавлен!", fg="#006600")
                        contact = self._client.contacts.get(uin)
                        if contact and not nick:
                            stranger = self._strangers.get(uin)
                            resolved_nick = (stranger.name if stranger and stranger.name != uin else "") \
                                            or contact.name or ""
                            if resolved_nick and resolved_nick != uin:
                                contact.name = resolved_nick
                            else:
                                if self._loop:
                                    if not hasattr(self, "_pending_nick_fetch"):
                                        self._pending_nick_fetch = {}
                                    self._pending_nick_fetch[uin] = "roster"
                                    asyncio.run_coroutine_threadsafe(
                                        self._client.request_user_info(uin), self._loop)
                        if contact:
                            if gid not in self._group_lists:
                                grp = self._client.groups.get(gid)
                                if grp is None:
                                    grp = Group(group_id=gid, name="General")
                                self._add_group(grp)
                            if uin not in self._contact_rows:
                                self._add_contact(contact)
                            self._rebuild_group(gid)
                        if uin in self._strangers:
                            unread_count = self._unread_map.get(uin, 0)
                            self._remove_stranger(uin)
                            row = self._contact_rows.pop(uin, None)
                            if row and row.winfo_exists(): row.destroy()
                            self._contact_ico.pop(uin, None)
                            self._contact_namelbl.pop(uin, None)
                            self._contact_unread.pop(uin, None)
                            self._rebuild_group(STRANGERS_GROUP_ID)
                            if contact and uin not in self._contact_rows:
                                self._add_contact(contact)
                            self._rebuild_group(gid)
                            self._unread_map[uin] = unread_count
                            badge = self._contact_unread.get(uin)
                            if badge and badge.winfo_exists():
                                if unread_count:
                                    badge.configure(text=str(unread_count),
                                                    bg=PALETTE["unread_badge"], fg="#ffffff")
                                else:
                                    badge.configure(text="", bg=PALETTE["bg_list"],
                                                    fg=PALETTE["bg_list"])
                        self._update_main_title()
                        win.after(900, win.destroy)
                    else:
                        status_lbl.configure(text="✘ Ошибка добавления", fg="#cc0000")
                schedule_in_tk(self, on_done)
            threading.Thread(target=task, daemon=True).start()

        btn_f = tk.Frame(win, bg=PALETTE["bg_main"])
        btn_f.pack(pady=6)
        tk.Button(btn_f, text="Добавить", font=("Segoe UI Symbol", 9, "bold"),
                  bg="#3a7abf", fg="white", relief="groove", padx=14,
                  cursor="hand2", command=do_add).pack(side="left", padx=6)
        tk.Button(btn_f, text="Отмена", font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                  relief="groove", padx=10, cursor="hand2",
                  command=win.destroy).pack(side="left")
        place_near_parent(win, self)

    def _move_contact_dialog(self, contact):
        if not self._client or not self._loop: return
        groups = sorted(self._client.groups.values(), key=lambda g: g.name.lower())
        if len(groups) < 2:
            messagebox.showinfo("Перемещение", "Нет других групп для перемещения.", parent=self)
            return
        dlg = tk.Toplevel(self)
        dlg.title(f"Переместить {contact.display_name}")
        dlg.geometry("260x180")
        dlg.configure(bg=PALETTE["bg_main"])
        dlg.resizable(False, False); dlg.transient(self); dlg.grab_set()

        tk.Label(dlg, text="Выберите группу:", font=("Segoe UI Symbol", 9, "bold"),
                 bg=PALETTE["bg_main"]).pack(pady=(12, 4))
        listbox = tk.Listbox(dlg, font=("Segoe UI Symbol", 9), height=6,
                             selectmode="single", relief="groove", bd=1)
        listbox.pack(fill="x", padx=16, pady=4)
        group_ids = []
        for g in groups:
            if g.group_id != contact.group_id:
                listbox.insert("end", g.name)
                group_ids.append(g.group_id)
        if not group_ids:
            messagebox.showinfo("Перемещение", "Нет других групп.", parent=self)
            dlg.destroy(); return
        listbox.selection_set(0)

        def _do_move():
            idx = listbox.curselection()
            if not idx: return
            new_gid = group_ids[idx[0]]
            dlg.destroy()
            old_gid = contact.group_id
            def _after_move(ok, _old=old_gid, _new=new_gid, _uin=contact.uin):
                if ok:
                    def _redraw():
                        row = self._contact_rows.get(_uin)
                        if row and row.winfo_exists():
                            row.destroy()
                        self._contact_rows.pop(_uin, None)
                        contact_obj = self._client.contacts.get(_uin)
                        if contact_obj:
                            self._add_contact(contact_obj)
                        self._rebuild_group(_old); self._rebuild_group(_new)
                    schedule_in_tk(self, _redraw)
                else:
                    schedule_in_tk(self, lambda: messagebox.showerror(
                        "Ошибка", "Не удалось переместить контакт.", parent=self))
            fut = asyncio.run_coroutine_threadsafe(
                self._client.move_contact(contact.uin, new_gid), self._loop)
            fut.add_done_callback(
                lambda f: _after_move(f.result() if not f.exception() else False))

        btn_f = tk.Frame(dlg, bg=PALETTE["bg_main"])
        btn_f.pack(pady=6)
        tk.Button(btn_f, text="Переместить", font=("Segoe UI Symbol", 9, "bold"),
                  bg="#3a7abf", fg="white", relief="groove", padx=12,
                  cursor="hand2", command=_do_move).pack(side="left", padx=6)
        tk.Button(btn_f, text="Отмена", font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                  relief="groove", padx=10, cursor="hand2",
                  command=dlg.destroy).pack(side="left")

    def _rename_contact_dialog(self, contact):
        is_stranger = contact.uin in self._strangers
        in_roster   = self._client and contact.uin in self._client.contacts
        if not in_roster and not is_stranger: return

        dlg = tk.Toplevel(self)
        dlg.title(f"Переименовать {contact.display_name}")
        dlg.geometry("300x130")
        dlg.configure(bg=PALETTE["bg_main"])
        dlg.resizable(False, False); dlg.transient(self); dlg.grab_set()

        tk.Label(dlg, text=f"UIN: {contact.uin}", font=("Segoe UI Symbol", 8),
                 fg="#666666", bg=PALETTE["bg_main"]).pack(pady=(10, 0))
        tk.Label(dlg, text="Новое имя:", font=("Segoe UI Symbol", 9, "bold"),
                 bg=PALETTE["bg_main"]).pack(pady=(4, 2))
        nick_var = tk.StringVar(value=contact.display_name)
        entry    = tk.Entry(dlg, textvariable=nick_var, font=("Segoe UI Symbol", 10),
                            relief="groove", bd=2, width=28)
        entry.pack(padx=20, pady=2)
        entry.select_range(0, "end"); entry.focus_set()

        status_lbl = tk.Label(dlg, text="", font=("Segoe UI Symbol", 8),
                              bg=PALETTE["bg_main"])
        status_lbl.pack()

        def _do_rename():
            new_nick = nick_var.get().strip()
            if not new_nick:
                status_lbl.configure(text="Имя не может быть пустым", fg="#cc0000"); return
            if new_nick == contact.display_name:
                dlg.destroy(); return
            if is_stranger:
                contact.name = new_nick
                lbl = self._contact_namelbl.get(contact.uin)
                if lbl and lbl.winfo_exists(): lbl.configure(text=new_nick)
                if self._client:
                    raw = load_strangers(self._client.uin)
                    if contact.uin in raw:
                        raw[contact.uin]["name"] = new_nick
                        save_strangers(self._client.uin, raw)
                dlg.destroy(); return
            if not self._loop or not self._loop.is_running():
                status_lbl.configure(text="Нет подключения", fg="#cc0000"); return
            btn_ok.configure(state="disabled")
            status_lbl.configure(text="Сохранение...", fg="#0055aa")
            def task():
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        self._client.rename_contact(contact.uin, new_nick), self._loop)
                    ok = fut.result(timeout=12)
                except Exception: ok = False
                schedule_in_tk(self, lambda: _on_done(ok))
            def _on_done(ok: bool):
                if ok:
                    lbl = self._contact_namelbl.get(contact.uin)
                    if lbl and lbl.winfo_exists(): lbl.configure(text=contact.display_name)
                    cw = self._chat_win
                    if cw and cw.winfo_exists():
                        cw.refresh_contact_name(contact.uin, contact.display_name)
                    dlg.after(400, dlg.destroy)
                else:
                    btn_ok.configure(state="normal")
                    status_lbl.configure(text="Ошибка сохранения", fg="#cc0000")
            threading.Thread(target=task, daemon=True).start()

        btn_f  = tk.Frame(dlg, bg=PALETTE["bg_main"])
        btn_f.pack(pady=6)
        btn_ok = tk.Button(btn_f, text="Сохранить", font=("Segoe UI Symbol", 9, "bold"),
                           bg="#3a7abf", fg="white", relief="groove",
                           padx=12, cursor="hand2", command=_do_rename)
        btn_ok.pack(side="left", padx=6)
        tk.Button(btn_f, text="Отмена", font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                  relief="groove", padx=10, cursor="hand2",
                  command=dlg.destroy).pack(side="left")
        dlg.bind("<Return>", lambda e: _do_rename())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _remove_contact_confirm(self, contact):
        if not self._client: return
        if not messagebox.askyesno("Удалить контакт",
                f"Удалить {contact.display_name} ({contact.uin}) из контакт-листа?",
                icon="warning", parent=self):
            return
        if contact.uin in self._strangers:
            self._remove_stranger(contact.uin)
            self._remove_contact_row(contact); return
        def task():
            fut = asyncio.run_coroutine_threadsafe(
                self._client.remove_contact(contact.uin), self._loop)
            ok = fut.result(timeout=12)
            if ok:
                schedule_in_tk(self, lambda: self._remove_contact_row(contact))
            else:
                schedule_in_tk(self, lambda: messagebox.showerror(
                    "Ошибка", f"Не удалось удалить {contact.display_name}", parent=self))
        threading.Thread(target=task, daemon=True).start()

    def _remove_contact_row(self, contact):
        uin = contact.uin; gid = contact.group_id
        row = self._contact_rows.pop(uin, None)
        if row and row.winfo_exists(): row.destroy()
        self._contact_ico.pop(uin, None)
        self._contact_namelbl.pop(uin, None)
        self._contact_unread.pop(uin, None)
        self._contact_xsico.pop(uin, None)
        self._unread_map.pop(uin, None)
        self._rebuild_group(gid)
        self._refresh_strangers_group_visibility()
        self._update_main_title()

    # ── Строка статуса / заголовок ────────────────────────────────────────────
    def _update_status_bar(self):
        label = STATUS_LABELS.get(self._my_status, "В сети")
        color = STATUS_COLORS.get(self._my_status, "#000000")
        self._status_lbl.configure(text=label, fg=color)
        if hasattr(self, "_status_ico_lbl") and self._status_ico_lbl.winfo_exists():
            photo = get_status_photo(self._my_status)
            if photo:
                self._status_ico_lbl.configure(image=photo,
                                               width=STATUS_ICON_W, height=STATUS_ICON_H)
                self._status_ico_lbl._status_photo = photo
            else:
                self._status_ico_lbl.configure(image="", width=0)
                self._status_ico_lbl._status_photo = None
        if hasattr(self, "_statusbar_xs_lbl") and self._statusbar_xs_lbl.winfo_exists():
            cfg     = load_config()
            xs_name = cfg.get("xstatus_name", "")
            idx     = get_xstatus_index_by_name(xs_name) if xs_name else -1
            photo   = get_xstatus_photo(idx) if idx >= 0 else None
            if photo:
                self._statusbar_xs_lbl.configure(image=photo,
                                                 width=XSTATUS_ICON_W, height=XSTATUS_ICON_H)
                self._statusbar_xs_lbl._xstatus_photo = photo
            else:
                self._statusbar_xs_lbl.configure(image="", width=0, height=0)
                self._statusbar_xs_lbl._xstatus_photo = None
        self._update_tray_icon()

    def _update_main_title(self):
        cw    = self._chat_win
        total = cw.get_total_unread() if cw and cw.winfo_exists() \
                else sum(self._unread_map.values())
        uin_str = self._client.uin if self._client else "ICQ"
        self.title(f"({total}) {uin_str}" if total else uin_str)
        if self._tray_icon:
            try:
                self._tray_icon.title = f"ICQ — {total} непрочитанных" if total else "ICQ Client"
            except Exception: pass

    def _is_connected(self) -> bool:
        if not self._client or not self._loop: return False
        if not self._loop.is_running(): return False
        running   = getattr(self._client, '_running', False)
        connected = getattr(self._client, 'is_connected', running)
        if callable(connected): connected = connected()
        return bool(running or connected)

    # ── Смена статуса ─────────────────────────────────────────────────────────
    def _change_status(self):
        if self._status_dlg_win and self._status_dlg_win.winfo_exists():
            self._status_dlg_win.lift(); self._status_dlg_win.focus_force(); return
        dlg = StatusDialog(self, self._my_status, self._my_status_msg)
        self._status_dlg_win = dlg
        self.wait_window(dlg)
        if not dlg.result: return
        s, msg, xs_name, xs_title, xs_desc = dlg.result
        if s == Status.OFFLINE:
            self._go_offline(); return
        self._my_status     = s
        self._my_status_msg = msg
        c = load_config()
        c["xstatus_name"]  = xs_name
        c["xstatus_title"] = xs_title
        c["xstatus_desc"]  = xs_desc
        save_config(c)
        self._update_status_bar()
        if self._is_connected():
            asyncio.run_coroutine_threadsafe(self._client.set_status(s, msg), self._loop)
            if xs_name:
                asyncio.run_coroutine_threadsafe(
                    self._client.set_xstatus(xs_name, xs_title, xs_desc), self._loop)
        else:
            self._reconnect_with_status()

    def _go_offline(self):
        self._my_status = Status.OFFLINE
        self._update_status_bar()
        client = self._client; loop = self._loop
        if client:
            try: client._stop_requested = True
            except Exception: pass
            try: client._running = False
            except Exception: pass
        if client and loop and loop.is_running():
            if hasattr(client, "stop") and callable(client.stop):
                try: asyncio.run_coroutine_threadsafe(client.stop(), loop)
                except Exception: pass
        if client:
            for contact in client.contacts.values():
                contact.status = Status.OFFLINE; contact.xstatus = ""; contact.xstatus_msg = ""
                self._update_contact_row(contact)
        self._session_id += 1
        self._client = None; self._loop = None

    def _reconnect_with_status(self):
        cfg     = load_config()
        uin     = (self._client.uin if self._client else None) or cfg.get("uin", "")
        pwd     = cfg.get("password", "")
        if not uin or not pwd:
            self._show_login(); return
        srv     = cfg.get("server", "195.66.114.37:5190")
        host, port = srv, 5190
        if ":" in srv:
            parts = srv.rsplit(":", 1); host = parts[0]
            try: port = int(parts[1])
            except ValueError: pass
        self._status_lbl.configure(text="Подключение...", fg=PALETTE["fg_offline"])
        self._connect(uin, pwd, host, port)

    def _relogin(self):
        cfg = load_config(); dlg = LoginDialog(self, cfg); self.wait_window(dlg)
        if dlg.result:
            uin, pwd, host, port = dlg.result; self._connect(uin, pwd, host, port)

    # ── Своя анкета ───────────────────────────────────────────────────────────
    def _on_self_info(self):
        if not self._client: return
        if self._my_info_win and self._my_info_win.winfo_exists():
            self._my_info_win.lift(); self._my_info_win.focus_force(); return
        win = UserInfoDialog(self, self._client.uin,
                             self._client.my_nick or self._client.uin, editable=True)
        self._my_info_win = win
        if self._client.my_info:
            win.load_info(self._client.my_info)
        else:
            win.set_status("Загружаю анкету с сервера...")
            asyncio.run_coroutine_threadsafe(self._client.request_my_info(), self._loop)
        def on_save(info: UserInfo):
            win.set_status("Сохраняю...")
            def task():
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.save_my_info(info), self._loop)
                ok = fut.result(timeout=12)
                schedule_in_tk(self, lambda: win.set_status(
                    "✔ Сохранено!" if ok else "✘ Ошибка сохранения",
                    color="#006600" if ok else "#cc0000"))
            threading.Thread(target=task, daemon=True).start()
        win.on_save = on_save

        def on_set_require_auth(require: bool):
            """Включает/выключает требование авторизации на сервере."""
            win.set_status("Применяю...", color="#0055aa")
            def task():
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.set_require_auth(require), self._loop)
                try:
                    ok = fut.result(timeout=12)
                except Exception:
                    ok = False
                def _update_status(ok=ok, require=require):
                    if win.winfo_exists():
                        win.set_status(
                            ("✔ Авторизация включена" if require else "✔ Авторизация отключена") if ok
                            else "✘ Ошибка — попробуйте ещё раз",
                            color="#006600" if ok else "#cc0000")
                schedule_in_tk(self, _update_status)
            threading.Thread(target=task, daemon=True).start()
        win.on_set_require_auth = on_set_require_auth
        # Состояние чекбокса — всегда из анкеты сервера (источник истины).
        # Если анкета ещё не загружена, чекбокс останется False до прихода on_my_info → load_info.
        if self._client and self._client.my_info:
            win.set_require_auth_state(bool(self._client.my_info.auth_required))

    def _search_contact(self):
        if not self._client: return
        if hasattr(self, "_search_win") and self._search_win and self._search_win.winfo_exists():
            self._search_win.lift(); self._search_win.focus_force(); return
        self._search_win = SearchDialog(self, self._client, self._loop)

    # ── Управление группами ───────────────────────────────────────────────────
    def _manage_groups(self):
        if not self._client: return
        if self._manage_grp_win and self._manage_grp_win.winfo_exists():
            self._manage_grp_win.lift(); self._manage_grp_win.focus_force(); return

        win = tk.Toplevel(self)
        self._manage_grp_win = win
        win.title("Управление группами")
        win.configure(bg=PALETTE["bg_main"])
        win.resizable(False, False); win.grab_set()

        tk.Label(win, text="⁂ Управление группами", font=("Segoe UI Symbol", 10, "bold"),
                 bg=PALETTE["title_bar"], fg="white").pack(fill="x")

        footer = tk.Frame(win, bg=PALETTE["bg_main"])
        footer.pack(side="bottom", fill="x", padx=12, pady=(4, 10))
        tk.Button(footer, text="➕ Создать", font=("Segoe UI Symbol", 9, "bold"),
                  bg="#3a7abf", fg="white", relief="groove", padx=10,
                  cursor="hand2", command=lambda: do_create()).pack(side="left", padx=(0, 4))
        tk.Button(footer, text="✘ Удалить выбранную", font=("Segoe UI Symbol", 9),
                  bg="#cc4444", fg="white", relief="groove", padx=10,
                  cursor="hand2", command=lambda: do_delete()).pack(side="left", padx=4)
        tk.Button(footer, text="Закрыть", font=("Segoe UI Symbol", 9), bg="#e0e0e0",
                  relief="groove", cursor="hand2",
                  command=win.destroy).pack(side="right")

        body = tk.Frame(win, bg=PALETTE["bg_main"], padx=12, pady=8)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Существующие группы:", font=("Segoe UI Symbol", 9, "bold"),
                 bg=PALETTE["bg_main"]).pack(anchor="w")
        list_frame = tk.Frame(body, bg=PALETTE["bg_list"], bd=1, relief="sunken")
        list_frame.pack(fill="both", expand=True, pady=(4, 6))
        listbox = tk.Listbox(list_frame, font=("Segoe UI Symbol", 9),
                             bg=PALETTE["bg_list"], fg=PALETTE["fg_group"],
                             selectbackground=PALETTE["select_bg"],
                             relief="flat", bd=0, activestyle="none", height=8)
        vsb = tk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); listbox.pack(fill="both", expand=True)

        def refresh_list():
            listbox.delete(0, "end")
            for g in sorted(self._client.groups.values(), key=lambda g: g.name.lower()):
                cnt = sum(1 for c in self._client.contacts.values() if c.group_id == g.group_id)
                listbox.insert("end", f"  {g.name}  ({cnt} контактов)  [id={g.group_id}]")
            listbox._group_list = sorted(self._client.groups.values(), key=lambda g: g.name.lower())

        refresh_list()
        tk.Frame(body, height=1, bg=PALETTE["border"]).pack(fill="x", pady=(2, 6))
        create_frame = tk.Frame(body, bg=PALETTE["bg_main"])
        create_frame.pack(fill="x")
        tk.Label(create_frame, text="Новая группа:", font=("Segoe UI Symbol", 9),
                 bg=PALETTE["bg_main"], anchor="w").pack(side="left")
        new_name_var   = tk.StringVar()
        new_name_entry = tk.Entry(create_frame, textvariable=new_name_var,
                                  font=("Segoe UI Symbol", 9), relief="groove", bd=2)
        new_name_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        status_lbl = tk.Label(body, text="", font=("Segoe UI Symbol", 8), bg=PALETTE["bg_main"])
        status_lbl.pack(anchor="w", pady=(4, 0))
        win.update_idletasks()
        win.minsize(win.winfo_reqwidth(), win.winfo_reqheight())
        place_near_parent(win, self)

        def do_create():
            name = new_name_var.get().strip()
            if not name:
                status_lbl.configure(text="⚠ Введите название группы", fg="#cc0000"); return
            if any(g.name.lower() == name.lower() for g in self._client.groups.values()):
                status_lbl.configure(text="⚠ Группа с таким именем уже существует", fg="#cc0000"); return
            status_lbl.configure(text="Создаю...", fg="#0055aa"); win.update()
            def task():
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.create_group(name), self._loop)
                try: ok, group = fut.result(timeout=12)
                except Exception as e: ok, group = False, None; log.error(f"create_group error: {e}")
                def on_done():
                    if ok and group:
                        self._add_group(group); self._rebuild_list()
                        new_name_var.set(""); refresh_list()
                        status_lbl.configure(text=f"✔ Группа «{group.name}» создана", fg="#006600")
                    else:
                        status_lbl.configure(text="✘ Ошибка создания группы", fg="#cc0000")
                schedule_in_tk(self, on_done)
            threading.Thread(target=task, daemon=True).start()

        def do_delete():
            sel = listbox.curselection()
            if not sel:
                status_lbl.configure(text="⚠ Выберите группу для удаления", fg="#cc0000"); return
            groups_list = getattr(listbox, "_group_list", [])
            if not groups_list or sel[0] >= len(groups_list): return
            group   = groups_list[sel[0]]
            members = [c for c in self._client.contacts.values() if c.group_id == group.group_id]
            if members:
                status_lbl.configure(
                    text=f"⚠ В группе {len(members)} контакт(ов). Сначала удалите их.", fg="#cc0000"); return
            if not messagebox.askyesno("Удалить группу", f"Удалить группу «{group.name}»?",
                                       icon="warning", parent=win): return
            status_lbl.configure(text="Удаляю...", fg="#0055aa"); win.update()
            def task():
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.delete_group(group.group_id), self._loop)
                try: ok = fut.result(timeout=12)
                except Exception as e: ok = False; log.error(f"delete_group error: {e}")
                def on_done():
                    if ok:
                        frame = self._group_frames.pop(group.group_id, None)
                        if frame:
                            try: frame.destroy()
                            except Exception: pass
                        self._group_labels.pop(group.group_id, None)
                        self._group_lists.pop(group.group_id, None)
                        self._group_open.pop(group.group_id, None)
                        refresh_list()
                        status_lbl.configure(text=f"✔ Группа «{group.name}» удалена", fg="#006600")
                    else:
                        status_lbl.configure(text="✘ Ошибка удаления группы", fg="#cc0000")
                schedule_in_tk(self, on_done)
            threading.Thread(target=task, daemon=True).start()

    # ── Настройки ─────────────────────────────────────────────────────────────
    def _settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift(); self._settings_win.focus_force(); return

        win = tk.Toplevel(self)
        self._settings_win = win
        win.title("Настройки")
        win.configure(bg=PALETTE["bg_main"])
        win.resizable(False, False)

        tk.Label(win, text="⚙ Настройки", font=(_uf()[0], _uf()[1] + 1, "bold"),
                 bg=PALETTE["title_bar"], fg="white").pack(fill="x")

        btn_f = tk.Frame(win, bg=PALETTE["bg_main"])
        btn_f.pack(side="bottom", pady=8, padx=12, fill="x")
        tk.Button(btn_f, text="☺ Сменить аккаунт", font=_uf(delta=-1), bg="#e8e0d0",
                  relief="groove", cursor="hand2",
                  command=lambda: [win.destroy(), self._relogin()]).pack(side="left", padx=(0, 4))
        tk.Button(btn_f, text="Закрыть", command=win.destroy, bg="#e0e0e0",
                  font=_uf(), relief="groove", cursor="hand2").pack(side="right")

        body = tk.Frame(win, bg=PALETTE["bg_main"], padx=14, pady=10)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Подключение", font=_uf(bold=True),
                 bg=PALETTE["bg_main"], fg=PALETTE["accent"]).grid(
                     row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        tk.Label(body, text="Сервер:", font=_uf(),
                 bg=PALETTE["bg_main"]).grid(row=1, column=0, sticky="w", pady=3)
        tk.Label(body,
                 text=f"{self._client.server}:{self._client.port}" if self._client else "—",
                 font=_uf(), bg=PALETTE["bg_main"], fg=PALETTE["accent"]).grid(
                     row=1, column=1, sticky="w", padx=8)
        tk.Frame(body, height=1, bg=PALETTE["border"]).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(10, 6))

        tk.Label(body, text="Шрифт переписки (чат)", font=_uf(bold=True),
                 bg=PALETTE["bg_main"], fg=PALETTE["accent"]).grid(
                     row=3, column=0, columnspan=2, sticky="w", pady=(0, 5))

        import tkinter.font as _tkf
        all_fonts = sorted(set(_tkf.families()))
        from config import _CHAT_FONT_FAMILY, _CHAT_FONT_SIZE, _CHAT_FONT_BOLD
        from config import _UI_FONT_FAMILY, _UI_FONT_SIZE

        tk.Label(body, text="Семейство:", font=_uf(), bg=PALETTE["bg_main"]).grid(
            row=4, column=0, sticky="w", pady=3)
        chat_fam_var = tk.StringVar(value=_CHAT_FONT_FAMILY)
        chat_fam_cb  = ttk.Combobox(body, textvariable=chat_fam_var,
                                    values=all_fonts, width=25, state="normal")
        chat_fam_cb.grid(row=4, column=1, sticky="w", padx=8, pady=3)

        tk.Label(body, text="Размер:", font=_uf(), bg=PALETTE["bg_main"]).grid(
            row=5, column=0, sticky="w", pady=3)
        chat_size_var = tk.IntVar(value=_CHAT_FONT_SIZE)
        sf = tk.Frame(body, bg=PALETTE["bg_main"])
        sf.grid(row=5, column=1, sticky="w", padx=8)
        tk.Button(sf, text="−", font=_uf(bold=True), bg="#d0d0d0", relief="groove",
                  width=2, cursor="hand2",
                  command=lambda: chat_size_var.set(max(6, chat_size_var.get()-1))).pack(side="left")
        tk.Label(sf, textvariable=chat_size_var, width=3, font=_uf(bold=True),
                 bg=PALETTE["bg_main"], anchor="center").pack(side="left", padx=4)
        tk.Button(sf, text="+", font=_uf(bold=True), bg="#d0d0d0", relief="groove",
                  width=2, cursor="hand2",
                  command=lambda: chat_size_var.set(min(32, chat_size_var.get()+1))).pack(side="left")

        chat_bold_var = tk.BooleanVar(value=_CHAT_FONT_BOLD)
        tk.Checkbutton(body, text="Жирный текст в чате", variable=chat_bold_var,
                       font=_uf(), bg=PALETTE["bg_main"],
                       activebackground=PALETTE["bg_main"], cursor="hand2").grid(
                           row=6, column=0, columnspan=2, sticky="w", pady=3)

        tk.Label(body, text="Предпросмотр:", font=_uf(), bg=PALETTE["bg_main"]).grid(
            row=7, column=0, sticky="nw", pady=3)
        prev_frame = tk.Frame(body, bg=PALETTE["msg_in_bg"], bd=1, relief="sunken")
        prev_frame.grid(row=7, column=1, sticky="ew", padx=8, pady=3)
        prev_lbl = tk.Label(prev_frame,
                            text="Привет! Как дела? :)\nHello world — preview",
                            font=(_CHAT_FONT_FAMILY, _CHAT_FONT_SIZE),
                            bg=PALETTE["msg_in_bg"], fg=PALETTE["msg_text"],
                            anchor="w", justify="left", padx=6, pady=4, wraplength=200)
        prev_lbl.pack(fill="x")

        def _update_prev(*_):
            fam = chat_fam_var.get() or "Segoe UI"
            sz  = chat_size_var.get()
            try:
                prev_lbl.configure(font=(fam, sz, "bold") if chat_bold_var.get() else (fam, sz))
            except Exception: pass

        chat_fam_var.trace_add("write", _update_prev)
        chat_size_var.trace_add("write", _update_prev)
        chat_bold_var.trace_add("write", _update_prev)

        tk.Frame(body, height=1, bg=PALETTE["border"]).grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(10, 6))

        tk.Label(body, text="Шрифт интерфейса (список, кнопки)", font=_uf(bold=True),
                 bg=PALETTE["bg_main"], fg=PALETTE["accent"]).grid(
                     row=9, column=0, columnspan=2, sticky="w", pady=(0, 5))
        tk.Label(body, text="Семейство:", font=_uf(), bg=PALETTE["bg_main"]).grid(
            row=10, column=0, sticky="w", pady=3)
        ui_fam_var = tk.StringVar(value=_UI_FONT_FAMILY)
        ui_fam_cb  = ttk.Combobox(body, textvariable=ui_fam_var,
                                   values=all_fonts, width=25, state="normal")
        ui_fam_cb.grid(row=10, column=1, sticky="w", padx=8, pady=3)

        tk.Label(body, text="Размер:", font=_uf(), bg=PALETTE["bg_main"]).grid(
            row=11, column=0, sticky="w", pady=3)
        ui_size_var = tk.IntVar(value=_UI_FONT_SIZE)
        uf2 = tk.Frame(body, bg=PALETTE["bg_main"])
        uf2.grid(row=11, column=1, sticky="w", padx=8)
        tk.Button(uf2, text="−", font=_uf(bold=True), bg="#d0d0d0", relief="groove",
                  width=2, cursor="hand2",
                  command=lambda: ui_size_var.set(max(6, ui_size_var.get()-1))).pack(side="left")
        tk.Label(uf2, textvariable=ui_size_var, width=3, font=_uf(bold=True),
                 bg=PALETTE["bg_main"], anchor="center").pack(side="left", padx=4)
        tk.Button(uf2, text="+", font=_uf(bold=True), bg="#d0d0d0", relief="groove",
                  width=2, cursor="hand2",
                  command=lambda: ui_size_var.set(min(24, ui_size_var.get()+1))).pack(side="left")

        tk.Frame(body, height=1, bg=PALETTE["border"]).grid(
            row=12, column=0, columnspan=2, sticky="ew", pady=(10, 6))

        apply_status = tk.Label(body, text="", font=_uf(delta=-1), bg=PALETTE["bg_main"])
        apply_status.grid(row=14, column=0, columnspan=2, sticky="w", pady=(4, 0))

        def _apply():
            import config as _cfg_mod
            _cfg_mod._CHAT_FONT_FAMILY = chat_fam_var.get() or "Segoe UI"
            _cfg_mod._CHAT_FONT_SIZE   = max(6, min(32, chat_size_var.get()))
            _cfg_mod._CHAT_FONT_BOLD   = chat_bold_var.get()
            _cfg_mod._UI_FONT_FAMILY   = ui_fam_var.get() or "Segoe UI"
            _cfg_mod._UI_FONT_SIZE     = max(6, min(24, ui_size_var.get()))
            cfg = load_config()
            cfg["chat_font_family"] = _cfg_mod._CHAT_FONT_FAMILY
            cfg["chat_font_size"]   = _cfg_mod._CHAT_FONT_SIZE
            cfg["chat_font_bold"]   = _cfg_mod._CHAT_FONT_BOLD
            cfg["ui_font_family"]   = _cfg_mod._UI_FONT_FAMILY
            cfg["ui_font_size"]     = _cfg_mod._UI_FONT_SIZE
            save_config(cfg)
            cw = self._chat_win
            if cw and cw.winfo_exists():
                for pane in cw._panes.values():
                    try: pane.apply_fonts()
                    except Exception: pass
            self.apply_ui_fonts()
            if win.winfo_exists():
                apply_status.configure(text="✔ Применено", fg="#006600")
                win.after(2000, lambda: apply_status.configure(text="")
                          if win.winfo_exists() else None)

        def _reset_defaults():
            chat_fam_var.set("Segoe UI"); chat_size_var.set(11)
            chat_bold_var.set(False); ui_fam_var.set("Segoe UI"); ui_size_var.set(10)

        btn_row = tk.Frame(body, bg=PALETTE["bg_main"])
        btn_row.grid(row=13, column=0, columnspan=2, sticky="w", pady=(4, 2))
        tk.Button(btn_row, text="✔ Применить шрифты", font=_uf(bold=True),
                  bg="#3a7abf", fg="white", relief="groove", padx=12,
                  cursor="hand2", command=_apply).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="↺ По умолчанию", font=_uf(),
                  bg="#e0e0e0", relief="groove", padx=8,
                  cursor="hand2", command=_reset_defaults).pack(side="left")

        body.columnconfigure(1, weight=1)
        win.update_idletasks()
        win.minsize(win.winfo_reqwidth(), win.winfo_reqheight())
        place_near_parent(win, self)

    # ── Уведомления об обрыве ─────────────────────────────────────────────────
    def _show_conn_error(self, message: str):
        if self._conn_notif:
            try: self._conn_notif.destroy()
            except Exception: pass
            self._conn_notif = None
        try:
            notif = ConnectionLostNotification(
                self, message, callback=lambda: self._reconnect_with_status())
            self._conn_notif  = notif
            notif.on_dismiss  = self._dismiss_conn_notif
        except Exception as e:
            log.error(f"_show_conn_error failed: {e}", exc_info=True)

    def _dismiss_conn_notif(self, notif):
        if self._conn_notif is notif:
            self._conn_notif = None
        try: notif.destroy()
        except Exception: pass