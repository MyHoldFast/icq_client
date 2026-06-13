"""
chat_window.py — ChatWindow: окно чата с вкладками.
"""
import tkinter as tk
from typing import Dict, Optional

from icq_core import ICQClient, Message

from config import load_config, save_config, _uf
from theme import PALETTE, place_near_parent
from resources import (
    get_xstatus_index_by_name, get_xstatus_photo,
    XSTATUS_ICON_W, XSTATUS_ICON_H,
)
from chat_pane import ChatPane


class ChatWindow(tk.Toplevel):
    def __init__(self, master, client: ICQClient):
        super().__init__(master)
        self.client = client
        self.title("Сообщения")
        self.geometry("720x600")
        self.minsize(480, 420)
        self.configure(bg=PALETTE["bg_main"])

        self._panes: Dict[str, ChatPane] = {}
        self._tab_buttons: Dict[str, tk.Frame] = {}
        self._active_uin: Optional[str] = None
        self._typing_users: Dict[str, bool] = {}
        self._unread: Dict[str, int] = {}

        cfg = load_config()
        self._send_mode = tk.StringVar(value=cfg.get("send_mode", "enter"))
        self._send_mode.trace_add("write", self._on_send_mode_change)
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        geom = cfg.get("chat_window_geometry", "")
        if geom:
            try:
                self.geometry(geom)
            except Exception:
                pass
        self.bind("<Configure>", self._on_resize)

    def _build_ui(self):
        self._header = tk.Frame(self, bg=PALETTE["toolbar_bg"], relief="flat", bd=0)
        self._header.pack(fill="x", side="top")

        icon_lbl = tk.Label(self._header, text="☘", font=("Segoe UI Symbol", 22),
                            bg=PALETTE["toolbar_bg"], fg=PALETTE["accent"])
        icon_lbl.pack(side="left", padx=6, pady=4)

        info_frame = tk.Frame(self._header, bg=PALETTE["toolbar_bg"])
        info_frame.pack(side="left", fill="x", expand=True, pady=3)

        name_row = tk.Frame(info_frame, bg=PALETTE["toolbar_bg"])
        name_row.pack(fill="x")
        self._header_xs_lbl = tk.Label(name_row, bg=PALETTE["toolbar_bg"], image="", bd=0, padx=2, pady=0)
        self._header_xs_lbl._xstatus_photo = None

        self.name_lbl = tk.Label(name_row, text=" ", font=("Segoe UI Symbol", 9, "bold"),
                                 bg=PALETTE["toolbar_bg"], anchor="w")
        self.name_lbl.pack(fill="x", side="left")

        self.xstatus_lbl = tk.Label(info_frame, text=" ", font=("Segoe UI Symbol", 8),
                                    bg=PALETTE["toolbar_bg"], fg="#884400", anchor="w")
        self.xstatus_lbl.pack(fill="x")

        self._uin_lbl = tk.Label(self._header, text=" ", font=("Segoe UI Symbol", 8, "bold"),
                                 bg=PALETTE["toolbar_bg"], fg=PALETTE["accent"])
        self._uin_lbl.pack(side="right", padx=8)

        tk.Frame(self, height=1, bg=PALETTE["border"]).pack(fill="x")

        self._tab_bar = tk.Frame(self, bg=PALETTE["toolbar_bg"])
        self._tab_bar.pack(fill="x", side="top")
        tk.Frame(self, height=1, bg=PALETTE["border"]).pack(fill="x", side="top")

        bottom = tk.Frame(self, bg=PALETTE["status_bar_bg"])
        bottom.pack(fill="x", side="bottom")

        tk.Label(bottom, text="☘", font=("Segoe UI Symbol", 11),
                 bg=PALETTE["status_bar_bg"], fg=PALETTE["accent"]).pack(side="left", padx=4)

        self._typing_status = tk.Label(bottom, text=" ", font=("Segoe UI Symbol", 8, "italic"),
                                       bg=PALETTE["status_bar_bg"], fg=PALETTE["typing_fg"])
        self._typing_status.pack(side="left", fill="x", expand=True)

        mode_frame = tk.Frame(bottom, bg=PALETTE["status_bar_bg"])
        mode_frame.pack(side="right", padx=6)
        tk.Label(mode_frame, text="Отправка: ", font=("Segoe UI Symbol", 7),
                 bg=PALETTE["status_bar_bg"], fg="#444444").pack(side="left")
        tk.Radiobutton(mode_frame, text="Enter", variable=self._send_mode, value="enter",
                       font=("Segoe UI Symbol", 7), bg=PALETTE["status_bar_bg"],
                       activebackground=PALETTE["status_bar_bg"], cursor="hand2").pack(side="left", padx=2)
        tk.Radiobutton(mode_frame, text="Ctrl+Enter", variable=self._send_mode, value="ctrl_enter",
                       font=("Segoe UI Symbol", 7), bg=PALETTE["status_bar_bg"],
                       activebackground=PALETTE["status_bar_bg"], cursor="hand2").pack(side="left", padx=2)

        tk.Button(bottom, text="➤ Отправить", font=("Segoe UI Symbol", 8, "bold"),
                  bg="#3a7abf", fg="white", relief="groove", bd=1, cursor="hand2",
                  command=self._send_active).pack(side="right", padx=4, pady=2)

        self._content = tk.Frame(self, bg=PALETTE["msg_in_bg"])
        self._content.pack(fill="both", expand=True)

    def _on_send_mode_change(self, *_):
        c = load_config()
        c["send_mode"] = self._send_mode.get()
        save_config(c)

    def _on_resize(self, event):
        if event.widget is self:
            try:
                c = load_config()
                c["chat_window_geometry"] = self.geometry()
                save_config(c)
            except Exception:
                pass

    def _on_close(self):
        if self._active_uin and self._active_uin in self._panes:
            self._panes[self._active_uin].pack_forget()
            self._set_tab_style(self._active_uin, active=False)
        self._active_uin = None
        self.withdraw()

    def open_contact_silent(self, contact):
        uin = contact.uin
        if uin in self._panes: return
        pane = ChatPane(self._content, contact, self.client, self._send_mode)
        self._panes[uin] = pane
        self._create_tab(uin, contact, active=False)

    def open_contact(self, contact):
        uin = contact.uin
        if uin not in self._panes:
            pane = ChatPane(self._content, contact, self.client, self._send_mode)
            self._panes[uin] = pane
            self._create_tab(uin, contact, active=True)
        self._switch_tab(uin)

    def _create_tab(self, uin, contact, active=False):
        tab_frame = tk.Frame(self._tab_bar, bg=PALETTE["tab_inactive"],
                             relief="raised", bd=1, cursor="hand2")
        tab_frame.pack(side="left", padx=1, pady=2)

        name_lbl = tk.Label(tab_frame, text=f" {contact.display_name}  ",
                            font=_uf(delta=-1), bg=PALETTE["tab_inactive"],
                            fg="#333333", cursor="hand2", padx=2, pady=2)
        name_lbl.pack(side="left")

        close_lbl = tk.Label(tab_frame, text="✕", font=_uf(delta=-2),
                             bg=PALETTE["tab_inactive"], fg="#666666", cursor="hand2", padx=2, pady=2)
        close_lbl.pack(side="left")

        self._tab_buttons[uin] = tab_frame
        tab_frame._name_lbl  = name_lbl
        tab_frame._close_lbl = close_lbl

        for w in (tab_frame, name_lbl):
            w.bind("<Button-1>", lambda e, u=uin: self._switch_tab(u))
            w.bind("<Button-2>", lambda e, u=uin: self.close_tab(u))
        close_lbl.bind("<Button-1>", lambda e, u=uin: self.close_tab(u))
        close_lbl.bind("<Enter>", lambda e, c=close_lbl: c.configure(fg="#cc0000"))
        close_lbl.bind("<Leave>", lambda e, c=close_lbl, u=uin:
                       c.configure(fg="#ffffff" if self._unread.get(u, 0) else "#666666"))
        self._set_tab_style(uin, active=active)

    def _switch_tab(self, uin: str):
        if self._active_uin == uin: return
        if self._active_uin and self._active_uin in self._panes:
            self._panes[self._active_uin].pack_forget()
            self._set_tab_style(self._active_uin, active=False)

        self._active_uin = uin
        pane = self._panes[uin]
        pane.pack(fill="both", expand=True)
        self._set_tab_style(uin, active=True)
        pane.focus_input()
        self._update_header(pane.contact)
        self._clear_unread(uin)

        if self._typing_users.get(uin):
            self._typing_status.configure(
                text=f"✍ {pane.contact.display_name} печатает...", fg=PALETTE["typing_fg"])
        else:
            self._typing_status.configure(text="")

    def _set_tab_style(self, uin: str, active: bool):
        tab = self._tab_buttons.get(uin)
        if not tab or not tab.winfo_exists(): return
        n = self._unread.get(uin, 0)
        if n:
            bg, fg, relief = PALETTE["tab_unread"], PALETTE["tab_unread_fg"], "raised"
        elif active:
            bg, fg, relief = PALETTE["tab_active"], "#000000", "sunken"
        else:
            bg, fg, relief = PALETTE["tab_inactive"], "#333333", "raised"
        tab.configure(bg=bg, relief=relief)
        tab._name_lbl.configure(bg=bg, fg=fg)
        tab._close_lbl.configure(bg=bg,
                                  fg="#ffffff" if n else ("#444444" if active else "#666666"))

    def close_tab(self, uin: str):
        if uin not in self._panes: return
        was_active = (self._active_uin == uin)
        uins = list(self._panes.keys())
        idx  = uins.index(uin)

        self._panes[uin].stop_animations()
        self._panes[uin].destroy()
        del self._panes[uin]
        self._tab_buttons[uin].destroy()
        del self._tab_buttons[uin]
        self._typing_users.pop(uin, None)
        self._unread.pop(uin, None)

        if was_active:
            self._active_uin = None
            remaining = list(self._panes.keys())
            if remaining:
                new_uin = remaining[max(0, idx - 1)]
                self._switch_tab(new_uin)
            else:
                self._clear_header()
                self.withdraw()

    def _update_header(self, contact):
        self.name_lbl.configure(text=f"{contact.display_name}")
        self._uin_lbl.configure(text=contact.uin)
        xs_parts = []
        if contact.xstatus: xs_parts.append(f"[{contact.xstatus}]")
        if contact.xstatus_msg: xs_parts.append(contact.xstatus_msg)
        self.xstatus_lbl.configure(text="xStatus:  " + "   ".join(xs_parts) if xs_parts else "")
        self.title(f"Сообщения — {contact.display_name}")
        if hasattr(self, "_header_xs_lbl") and self._header_xs_lbl.winfo_exists():
            xs_name = getattr(contact, "xstatus", "")
            photo   = None
            if xs_name:
                idx   = get_xstatus_index_by_name(xs_name)
                photo = get_xstatus_photo(idx) if idx >= 0 else None
            if photo:
                self._header_xs_lbl.configure(image=photo,
                                              width=XSTATUS_ICON_W, height=XSTATUS_ICON_H)
                self._header_xs_lbl._xstatus_photo = photo
                self._header_xs_lbl.pack(side="left")
            else:
                self._header_xs_lbl.pack_forget()
                self._header_xs_lbl.configure(image="", width=1, height=1)
                self._header_xs_lbl._xstatus_photo = None

    def _clear_header(self):
        self.name_lbl.configure(text="")
        self._uin_lbl.configure(text="")
        self.xstatus_lbl.configure(text="")
        self.title("Сообщения")
        if hasattr(self, "_header_xs_lbl") and self._header_xs_lbl.winfo_exists():
            self._header_xs_lbl.pack_forget()
            self._header_xs_lbl.configure(image="", width=1, height=1)
            self._header_xs_lbl._xstatus_photo = None

    def append_message(self, uin: str, msg: Message):
        pane = self._panes.get(uin)
        if pane:
            outgoing_nick = self.client.my_nick or "Я"
            pane.append_message(msg, outgoing_nick=outgoing_nick)
        if uin != self._active_uin and not msg.is_outgoing:
            self._unread[uin] = self._unread.get(uin, 0) + 1
            self._update_tab_badge(uin)
            if hasattr(self.master, "_on_unread_message"):
                self.master._on_unread_message(uin)

    def _update_tab_badge(self, uin: str):
        n   = self._unread.get(uin, 0)
        tab = self._tab_buttons.get(uin)
        if tab and tab.winfo_exists():
            pane  = self._panes.get(uin)
            name  = pane.contact.display_name if pane else uin
            badge = f" ({n})" if n else ""
            tab._name_lbl.configure(text=f" {name}{badge}  ")
        self._set_tab_style(uin, active=(uin == self._active_uin))

    def _clear_unread(self, uin: str):
        if self._unread.get(uin, 0) == 0: return
        self._unread[uin] = 0
        self._update_tab_badge(uin)
        if hasattr(self.master, "_on_unread_cleared"):
            self.master._on_unread_cleared(uin)

    def get_total_unread(self) -> int: return sum(self._unread.values())
    def get_unread(self, uin: str) -> int: return self._unread.get(uin, 0)

    def refresh_contact_name(self, uin: str, new_name: str):
        tab = self._tab_buttons.get(uin)
        if tab and tab.winfo_exists() and hasattr(tab, "_name_lbl"):
            badge = ""
            n = self._unread.get(uin, 0)
            if n: badge = f" ({n})"
            tab._name_lbl.configure(text=f" {new_name}{badge}  ")
        if self._active_uin == uin:
            pane = self._panes.get(uin)
            if pane and pane.contact:
                pane.contact.name = new_name
                self._update_header(pane.contact)

    def update_contact(self, contact):
        pane = self._panes.get(contact.uin)
        if pane:
            pane.contact = contact
            tab = self._tab_buttons.get(contact.uin)
            if tab and tab.winfo_exists():
                n     = self._unread.get(contact.uin, 0)
                badge = f" ({n})" if n else ""
                tab._name_lbl.configure(text=f" {contact.display_name}{badge}  ")
        if self._active_uin == contact.uin: self._update_header(contact)

    def show_typing(self, uin: str, is_typing: bool):
        self._typing_users[uin] = is_typing
        if uin != self._active_uin: return
        pane = self._panes.get(uin)
        if not pane: return
        if is_typing:
            self._typing_status.configure(
                text=f"✍ {pane.contact.display_name} печатает...", fg=PALETTE["typing_fg"])
        else:
            self._typing_status.configure(text="")

    def has_contact(self, uin: str) -> bool: return uin in self._panes

    def _send_active(self):
        if self._active_uin:
            pane = self._panes.get(self._active_uin)
            if pane: pane._send_message()
