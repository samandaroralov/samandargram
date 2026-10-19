"""
╔══════════════════════════════════════════════╗
║               SAMANDARGRAM                   ║
║   Telethon (MTProto)  +  Textual (TUI)       ║
╚══════════════════════════════════════════════╝

Ishlatish : python samandargram.py
Talablar  : pip install telethon textual

Imkoniyatlar:
  • Chatlar, guruhlar, kanallar, botlar + kategoriyalar (Ctrl+T)
  • Global qidiruv (Ctrl+F / tugma) — hali a'zo bo'lmaganlar ham
  • Media gallery (Ctrl+G / tugma) — bosilganda avtomatik lokal ochiladi
  • Rasm, video, audio — barchasi tashqi ko'ruvchida (eog, feh, VLC, va h.k.)
  • Responsive — telefon, planshet, desktop ekranlariga moslashadi
  • GIF va stikerlar ko'rinmaydi / ochilmaydi
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOZLAMALAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import asyncio
import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


API_ID   = _env_int("TG_API_ID", 28462060)
API_HASH = os.getenv("TG_API_HASH", "9286cc15e42a0af5d90da96e4d101d1e")
SESSION  = os.getenv("TG_SESSION", "samandargram")

DOWNLOAD_DIR = "downloads"

# ── Foydalanuvchi kategoriyalari ──────────────
USER_CATEGORIES = {
    "💼 Ish": ["work", "job", "office", "ish", "ishchi", "korporativ",
               "company", "team", "hr", "boss", "manager"],
    "👨‍👩‍👧 Oila": ["oila", "family", "ota", "ona", "aka", "opa", "singil",
                  "bola", "xotin", "er", "qarindosh", "mahalla"],
    "🤝 Do'stlar": ["do'st", "friend", "yaqin", "bro", "sis", "gang",
                    "squad", "crew", "homie"],
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from rich.markup import escape
from telethon import TelegramClient, events, errors
from telethon.tl.types import User, Chat, Channel
from telethon.tl.functions.contacts import SearchRequest as ContactSearchRequest

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import (
    Header, ListView, ListItem,
    Label, Input, RichLog, Static, Button,
)
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Konstantlar
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAT_FILE = "samandargram_categories.json"

SYSFILTERS = [
    ("all",     "★ Barchasi"),
    ("unread",  "🔴 O'qilmagan"),
    ("user",    "◉ Shaxsiy"),
    ("group",   "◍ Guruhlar"),
    ("channel", "◈ Kanallar"),
    ("bot",     "⚙ Botlar"),
]

# Tashqi ko'ruvchida ochiladigan kengaytmalar (rasm, video, audio)
_LOCAL_EXTS = {
    # Rasmlar
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".heic", ".heif", ".ico", ".svg",
    # Videolar
    ".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv", ".m4v",
    ".3gp", ".ts", ".mpg", ".mpeg", ".ogv",
    # Audiolар
    ".mp3", ".ogg", ".wav", ".flac", ".aac", ".m4a", ".opus", ".wma",
    ".mid", ".midi",
}

# Brauzerda ochiladigan kengaytmalar (faqat hujjatlar)
_BROWSER_EXTS = {".html", ".htm", ".pdf", ".epub"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Yordamchi funksiyalar
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _name(entity) -> str:
    if isinstance(entity, User):
        parts = [entity.first_name or "", entity.last_name or ""]
        n = " ".join(p for p in parts if p).strip()
        return n or entity.username or str(entity.id)
    if isinstance(entity, (Chat, Channel)):
        return entity.title or str(entity.id)
    return str(entity)


def _ts(dt: Optional[datetime]) -> str:
    return dt.strftime("%H:%M") if dt else "??:??"


def _is_bot(entity) -> bool:
    return isinstance(entity, User) and bool(getattr(entity, "bot", False))


def _dtype(entity) -> str:
    if isinstance(entity, User):
        return "bot" if _is_bot(entity) else "user"
    if isinstance(entity, Channel) and entity.broadcast:
        return "channel"
    return "group"


def _icon(entity) -> str:
    return {"user": "◉", "channel": "◈", "group": "◍", "bot": "⚙"}.get(
        _dtype(entity), "◌")


def _col(entity) -> str:
    return {
        "user": "#00d4ff", "bot": "#c084fc",
        "group": "#39ff14", "channel": "#ffb700",
    }.get(_dtype(entity), "#8aaabf")


def _short(text: str, size: int) -> str:
    text = text or ""
    return text[:size - 1] + "…" if len(text) > size else text


# ── MEDIA aniqlash (GIF va stiker → None) ─────
def _media_info(message) -> Optional[str]:
    """
    Media turini aniqlash.
    Stiker va GIF → None (ko'rinmaydi, ochilmaydi).
    """
    m = message

    # Stiker — ko'rinmaydi
    if getattr(m, "sticker", None):
        return None

    if getattr(m, "photo", None):
        return "📷 Rasm"
    if getattr(m, "video", None):
        return "🎬 Video"
    if getattr(m, "voice", None):
        return "🎤 Ovozli xabar"
    if getattr(m, "video_note", None):
        return "📹 Video xabar"
    if getattr(m, "audio", None):
        return "🎵 Audio"

    if getattr(m, "document", None):
        mime = ""
        try:
            mime = m.file.mime_type or ""
        except Exception:
            pass
        # GIF — ko'rinmaydi
        if "gif" in mime.lower():
            return None
        fname = ""
        try:
            fname = m.file.name or ""
        except Exception:
            pass
        return f"📄 {fname or 'Fayl'}"

    return None


def _has_media(message) -> bool:
    return _media_info(message) is not None


def _file_size_str(message) -> str:
    try:
        sz = message.file.size or 0
        if sz > 1024 * 1024:
            return f"{sz / (1024 * 1024):.1f} MB"
        if sz > 1024:
            return f"{sz / 1024:.1f} KB"
        return f"{sz} B"
    except Exception:
        return ""


def _file_name_str(message) -> str:
    try:
        return message.file.name or ""
    except Exception:
        return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Kategoriya menejeri
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class CategoryManager:
    def __init__(self):
        self.path = Path(CAT_FILE)
        self._manual: dict = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()
                if isinstance(v, str) and v.strip()}

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._manual, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    def assign(self, dialog_id: int, cat_name: str) -> None:
        self._manual[str(dialog_id)] = cat_name
        self._save()

    def remove(self, dialog_id: int) -> None:
        self._manual.pop(str(dialog_id), None)
        self._save()

    def get(self, dialog_id: int, dialog_name: str) -> Optional[str]:
        manual = self._manual.get(str(dialog_id))
        if manual:
            return manual
        low = (dialog_name or "").lower()
        for cat, keywords in USER_CATEGORIES.items():
            if any(kw in low for kw in keywords):
                return cat
        return None

    def all_names(self) -> list:
        names = list(USER_CATEGORIES.keys())
        for v in self._manual.values():
            if v not in names:
                names.append(v)
        return names


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# StatusBar
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class StatusBar(Static):
    status = reactive("Yuklanmoqda…")

    def render(self) -> str:
        now = datetime.now().strftime("%H:%M:%S")
        return f" ⬡ SAMANDARGRAM  │  {self.status}  │  {now} "


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Asosiy ilova
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TelegramTUI(App):
    CSS = """
    $bg:          #0a0e14;
    $bg2:         #0f1520;
    $bg3:         #141c2b;
    $bg4:         #101827;
    $border:      #1e3a5f;
    $neon-blue:   #00d4ff;
    $neon-green:  #39ff14;
    $neon-amber:  #ffb700;
    $neon-pink:   #ff2d78;
    $neon-purple: #c084fc;
    $text-dim:    #3d5570;
    $text-mid:    #7a9abf;
    $text-hi:     #cce8ff;
    $text-bright: #ffffff;

    Screen { background: $bg; layout: vertical; }

    Header {
        background: $bg2;
        color: $neon-blue;
        text-style: bold;
        border-bottom: tall $border;
        height: 2;
    }

    #body { layout: horizontal; height: 1fr; }

    /* ── Sidebar (RESPONSIVE) ── */
    #sidebar {
        width: 34;
        min-width: 16;
        background: $bg2;
        border-right: tall $border;
        layout: vertical;
    }
    #sidebar-header {
        height: 2;
        background: $bg3;
        border-bottom: tall $border;
        content-align: center middle;
        color: $neon-blue;
        text-style: bold;
    }

    /* ── Tugmalar paneli ── */
    #sidebar-buttons {
        height: 2;
        layout: horizontal;
        background: $bg3;
        border-bottom: tall $border;
        padding: 0;
    }
    #btn-search, #btn-media-gallery {
        width: 1fr;
        height: 1;
        background: $bg3;
        text-style: bold;
        border: none;
        padding: 0;
    }
    #btn-search { color: $neon-pink; }
    #btn-media-gallery { color: $neon-purple; }
    #btn-search:hover, #btn-media-gallery:hover {
        background: $bg4;
        color: $text-bright;
    }

    /* ── Qidiruv paneli ── */
    #search-area {
        height: 3;
        layout: horizontal;
        background: $bg3;
        border-bottom: tall $neon-pink;
        padding: 0 1;
        align: left middle;
        display: none;
    }
    #search-area.visible {
        display: block; layout: horizontal; height: 3;
        align: left middle; padding: 0 1;
    }
    #search-prefix { width: 3; color: $neon-pink; text-style: bold; content-align: left middle; }
    #search-input {
        width: 1fr; background: $bg3; color: $text-bright;
        border: tall $neon-pink; padding: 0 1; height: 3;
    }
    #search-input:focus { border: tall $neon-pink; }

    /* Kategoriya ro'yxati */
    #cat-list {
        width: 100%; height: auto; background: $bg3;
        border-bottom: tall $border;
    }
    #cat-list > ListItem { padding: 0 2; height: 1; background: $bg3; color: $text-mid; }
    #cat-list > ListItem:hover { background: $bg4; color: $text-hi; }
    #cat-list > ListItem.--highlight {
        background: $bg4; color: $neon-blue; text-style: bold;
        border-left: tall $neon-blue;
    }

    /* Chat ro'yxati */
    #chat-list {
        height: 1fr; background: $bg2;
        scrollbar-color: $border; scrollbar-background: $bg2;
    }
    #chat-list > ListItem {
        padding: 0 1; height: 2; background: $bg2;
        border-bottom: tall $bg3; content-align: left middle;
    }
    #chat-list > ListItem:hover { background: $bg3; }
    #chat-list > ListItem.--highlight { background: $bg3; border-left: tall $neon-blue; }

    #sidebar-footer {
        height: 1; background: $bg3; border-top: tall $border;
        color: $text-dim; content-align: center middle;
    }

    /* ── O'ng panel ── */
    #right { layout: vertical; width: 1fr; background: $bg; }

    #chat-header {
        height: 3; background: $bg2; border-bottom: tall $border;
        layout: horizontal; padding: 0 2; align: left middle;
    }
    #header-icon { width: 3; color: $neon-blue; text-style: bold; content-align: left middle; }
    #header-name { width: 1fr; color: $text-bright; text-style: bold; content-align: left middle; }
    #header-cat  { width: 18; color: $neon-amber; content-align: center middle; }
    #header-meta { width: 20; color: $text-dim; content-align: right middle; }

    #message-log {
        height: 1fr; background: $bg; padding: 1 2;
        scrollbar-color: $border; scrollbar-background: $bg;
    }

    /* ── MEDIA GALLERY paneli ── */
    #media-panel {
        height: 12;
        background: $bg3;
        border-top: tall $neon-purple;
        layout: vertical;
        display: none;
    }
    #media-panel.visible { display: block; }
    #media-panel-header {
        height: 1;
        background: $bg4;
        color: $neon-purple;
        text-style: bold;
        content-align: center middle;
    }
    #media-list { height: 1fr; background: $bg3; }
    #media-list > ListItem {
        padding: 0 2; height: 1; background: $bg3; color: $text-hi;
    }
    #media-list > ListItem:hover { background: $bg4; color: $text-bright; }
    #media-list > ListItem.--highlight {
        background: $bg4; color: $neon-purple;
        border-left: tall $neon-purple;
    }

    /* ── Compose area ── */
    #compose-area {
        height: 4; layout: horizontal; background: $bg2;
        border-top: tall $border; padding: 0 1; align: left middle;
    }
    #compose-prefix { width: 4; color: $neon-green; text-style: bold; content-align: left middle; }
    #msg-input {
        width: 1fr; background: $bg3; color: $text-bright;
        border: tall $border; padding: 0 1; height: 3;
    }
    #msg-input:focus { border: tall $neon-blue; }

    /* Kategoriya input */
    #cat-input-area {
        height: 4; layout: horizontal; background: $bg3;
        border-top: tall $neon-amber; padding: 0 1;
        align: left middle; display: none;
    }
    #cat-input-area.visible {
        display: block; layout: horizontal; height: 4;
        align: left middle; padding: 0 1;
    }
    #cat-prefix { width: 18; color: $neon-amber; content-align: left middle; }
    #cat-input {
        width: 1fr; background: $bg3; color: $text-bright;
        border: tall $neon-amber; padding: 0 1; height: 3;
    }

    #send-hint { width: 40; color: $text-dim; content-align: right middle; }

    StatusBar {
        height: 1; background: $bg3; color: $neon-blue;
        text-align: center; dock: bottom;
    }
    """

    BINDINGS = [
        Binding("ctrl+c",  "quit",           "Chiqish"),
        Binding("ctrl+q",  "quit",           "Chiqish",     show=False),
        Binding("ctrl+r",  "reload",         "Yangilash"),
        Binding("ctrl+f",  "search",         "🔍 Qidiruv"),
        Binding("ctrl+g",  "media_gallery",  "📷 Media"),
        Binding("ctrl+m",  "view_media",     "⬇ Oxirgi media"),
        Binding("ctrl+t",  "tag_chat",       "Kategoriya"),
        Binding("ctrl+u",  "untag_chat",     "Tag olib tashlash", show=False),
        Binding("ctrl+d",  "delete_message", "Xabarni o'chirish"),
        Binding("ctrl+x",  "delete_dialog",  "Chatni o'chirish"),
        Binding("escape",  "close_overlays", "",             show=False),
    ]

    def __init__(self, client: TelegramClient):
        super().__init__()
        self.tg = client
        self._all: list = []
        self._shown: list = []
        self._active_id: Optional[int] = None
        self._active_entity = None
        self._me = None
        self._cur_filter = "all"
        self._catmgr = CategoryManager()
        self._unread_ids: set = set()
        self._cat_index: dict = {}
        self._history_messages: list = []
        self._pending_delete: Optional[tuple[str, int]] = None
        # Qidiruv
        self._search_query: str = ""
        self._global_results: list = []
        self._search_debounce_task: Optional[asyncio.Task] = None
        # Media gallery
        self._media_messages: list = []
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # ── Tuzilma ────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("⬡  SAMANDARGRAM", id="sidebar-header")

                # Tugmalar paneli
                with Horizontal(id="sidebar-buttons"):
                    yield Button("🔍 Qidiruv", id="btn-search", variant="default")
                    yield Button("📷 Media", id="btn-media-gallery", variant="default")

                # Qidiruv paneli
                with Horizontal(id="search-area"):
                    yield Static("🔍", id="search-prefix")
                    yield Input(
                        placeholder="Qidirish… (Enter=global)",
                        id="search-input",
                    )

                yield ListView(id="cat-list")
                yield ListView(id="chat-list")
                yield Static("", id="sidebar-footer")

            with Vertical(id="right"):
                with Horizontal(id="chat-header"):
                    yield Static("◌",             id="header-icon")
                    yield Static("Chat tanlang…", id="header-name")
                    yield Static("",              id="header-cat")
                    yield Static("",              id="header-meta")

                yield RichLog(id="message-log", highlight=True, markup=True, wrap=True)

                # Media gallery paneli
                with Vertical(id="media-panel"):
                    yield Static(
                        "📷 MEDIA  (bosing → lokal ochiladi, Esc=yopish)",
                        id="media-panel-header",
                    )
                    yield ListView(id="media-list")

                with Horizontal(id="cat-input-area"):
                    yield Static("📂 Kategoriya: ", id="cat-prefix")
                    yield Input(
                        placeholder="nom yozing (Enter=saqlash, Esc=bekor)",
                        id="cat-input",
                    )

                with Horizontal(id="compose-area"):
                    yield Static("›", id="compose-prefix")
                    yield Input(placeholder="Xabar yozing…", id="msg-input")
                    yield Static(
                        "Ctrl+G=media  Ctrl+F=qidiruv  /media N",
                        id="send-hint",
                    )

        yield StatusBar(id="statusbar")

    # ── RESPONSIVE: ekran o'lchamiga moslashish ───────────────────────────
    def on_resize(self, event) -> None:
        """Har qanday ekran o'lchamiga moslashish (telefon/planshet/desktop)."""
        try:
            width = self.size.width
            sidebar     = self.query_one("#sidebar")
            header_cat  = self.query_one("#header-cat")
            header_meta = self.query_one("#header-meta")
            send_hint   = self.query_one("#send-hint")
            cat_prefix  = self.query_one("#cat-prefix")
            search_pref = self.query_one("#search-prefix")

            if width < 55:
                sidebar.styles.width = 16
                header_cat.display  = False
                header_meta.display = False
                send_hint.display   = False
                cat_prefix.display  = False
                search_pref.display = False
            elif width < 90:
                sidebar.styles.width = 22
                header_cat.display  = True
                header_meta.display = False
                send_hint.display   = True
                cat_prefix.display  = True
                search_pref.display = True
            else:
                sidebar.styles.width = 34
                header_cat.display  = True
                header_meta.display = True
                send_hint.display   = True
                cat_prefix.display  = True
                search_pref.display = True
        except Exception:
            pass

    # ── Ishga tushish ──────────────────────────────────────────────────────
    async def on_mount(self) -> None:
        self._set_status("Telegram'ga ulanilmoqda…")
        self._me = await self.tg.get_me()
        await self._load_all()
        await self._build_cat_list()
        await self._rebuild_chat_list()
        self._register_handlers()
        self.on_resize(None)
        self._set_status(
            f"Kirdi: {_name(self._me)}  │  "
            f"Ctrl+F=qidiruv  Ctrl+G=media  Ctrl+T=kategoriya"
        )
        self.set_interval(1, self._tick)
        self.query_one("#msg-input", Input).focus()

    def _tick(self) -> None:
        sb = self.query_one("#statusbar", StatusBar)
        sb.status = sb.status

    def on_key(self, event) -> None:
        if not event.is_printable or self._active_entity is None:
            return
        if isinstance(getattr(self, "focused", None), Input):
            return
        cat_area = self.query_one("#cat-input-area")
        if cat_area.has_class("visible"):
            return
        search_area = self.query_one("#search-area")
        if search_area.has_class("visible"):
            return
        msg_input = self.query_one("#msg-input", Input)
        msg_input.focus()
        msg_input.insert_text_at_cursor(event.character or "")
        event.stop()

    # ── Dialoglarni yuklash ───────────────────────────────────────────────
    async def _load_all(self) -> None:
        self._set_status("Chatlar yuklanmoqda…")
        self._all = []
        self._unread_ids = set()
        async for d in self.tg.iter_dialogs(limit=200):
            self._all.append(d)
            if d.unread_count and d.unread_count > 0:
                self._unread_ids.add(d.id)

        def _order(d):
            t = _dtype(d.entity)
            return {"user": 0, "bot": 1, "group": 2, "channel": 3}.get(t, 4)

        self._all.sort(key=_order)

    # ── Kategoriya ro'yxati ───────────────────────────────────────────────
    async def _build_cat_list(self) -> None:
        lv = self.query_one("#cat-list", ListView)
        await lv.clear()

        for key, label in SYSFILTERS:
            if key == "unread":
                cnt = len(self._unread_ids)
                txt = f"{label} ({cnt})" if cnt else label
            else:
                txt = label
            await lv.append(ListItem(Label(f" {txt}"), id=f"sf-{key}"))

        await lv.append(ListItem(Label("[#1e3a5f]─────────────────[/]"), id="sep-cats"))

        all_cats = self._catmgr.all_names()
        self._cat_index = {}
        for i, cat in enumerate(all_cats):
            cnt = sum(1 for d in self._all
                      if self._catmgr.get(d.id, d.name or "") == cat)
            self._cat_index[i] = cat
            await lv.append(ListItem(
                Label(f" {escape(cat)} [#3d5570]({cnt})[/]"),
                id=f"uc-{i}",
            ))

        if self._cur_filter == "all":
            try:
                lv.index = 0
            except Exception:
                pass

    # ── Chat ro'yxati ─────────────────────────────────────────────────────
    def _apply_filter(self) -> None:
        f = self._cur_filter
        if f == "all":
            self._shown = list(self._all)
        elif f == "unread":
            self._shown = [d for d in self._all if d.id in self._unread_ids]
        elif f == "user":
            self._shown = [d for d in self._all if _dtype(d.entity) == "user"]
        elif f == "bot":
            self._shown = [d for d in self._all if _dtype(d.entity) == "bot"]
        elif f == "group":
            self._shown = [d for d in self._all if _dtype(d.entity) == "group"]
        elif f == "channel":
            self._shown = [d for d in self._all if _dtype(d.entity) == "channel"]
        else:
            self._shown = [d for d in self._all
                           if self._catmgr.get(d.id, d.name or "") == f]

        if self._search_query:
            self._shown = [d for d in self._shown
                           if self._search_query in (d.name or "").lower()]

    async def _rebuild_chat_list(self) -> None:
        self._apply_filter()
        lv = self.query_one("#chat-list", ListView)
        await lv.clear()

        for idx, d in enumerate(self._shown):
            ent  = d.entity
            icon = _icon(ent)
            col  = _col(ent)
            name = d.name or "(nomsiz)"
            disp = _short(name, 23)

            unread_badge = ""
            if d.id in self._unread_ids and d.unread_count:
                unread_badge = f" [bold #ff2d78]({d.unread_count})[/]"

            cat = self._catmgr.get(d.id, name)
            cat_badge = f" [#ffb700]{escape(_short(cat, 8))}[/]" if cat else ""

            label_text = (
                f"[bold {col}]{icon}[/] [white]{escape(disp)}[/]"
                f"{unread_badge}{cat_badge}"
            )
            await lv.append(ListItem(Label(label_text), id=f"dlg-{idx}"))

        if self._global_results:
            await lv.append(ListItem(
                Label("[bold #ff2d78]──── 🌐 GLOBAL NATIJALAR ────[/]"),
                id="gbl-sep",
            ))
            for idx, ent in enumerate(self._global_results):
                name  = _name(ent)
                icon  = _icon(ent)
                col   = _col(ent)
                dt    = _dtype(ent)
                t_lbl = {"user": "shaxsiy", "bot": "bot",
                         "group": "guruh",  "channel": "kanal"}.get(dt, "")
                uname = getattr(ent, "username", None)
                uname_txt = f" [@{escape(uname)}]" if uname else ""
                label_text = (
                    f"[bold {col}]{icon}[/] [white]{escape(_short(name, 18))}[/]"
                    f"{uname_txt} [#3d5570]{t_lbl}[/] [#ff2d78]🌐[/]"
                )
                await lv.append(ListItem(Label(label_text), id=f"gbl-{idx}"))

        n     = len(self._shown)
        total = len(self._all)
        urd   = len(self._unread_ids)
        gbl   = len(self._global_results)
        self.query_one("#sidebar-footer", Static).update(
            f"[#3d5570]◈ {n}/{total}  🔴{urd}  🌐{gbl}[/]"
        )

    # ── List tanlash ──────────────────────────────────────────────────────
    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        lv_id = event.list_view.id or ""
        iid   = event.item.id or ""

        if lv_id == "cat-list":
            if iid.startswith("sf-"):
                self._cur_filter = iid[3:]
                await self._rebuild_chat_list()
                self._set_status(f"Filtr: {self._cur_filter}  │  {len(self._shown)} ta")
            elif iid.startswith("uc-"):
                idx = int(iid[3:])
                cat = getattr(self, "_cat_index", {}).get(idx)
                if cat:
                    self._cur_filter = cat
                await self._rebuild_chat_list()
                self._set_status(f"Kategoriya: {self._cur_filter}  │  {len(self._shown)} ta")
            return

        if lv_id == "media-list":
            if iid.startswith("media-"):
                idx = int(iid[6:])
                if idx < len(self._media_messages):
                    await self._view_media_message(self._media_messages[idx])
            return

        if lv_id == "chat-list":
            if iid.startswith("gbl-"):
                idx = int(iid[4:])
                if idx < len(self._global_results):
                    await self._open_global_result(self._global_results[idx])
                return
            if iid == "gbl-sep":
                return

            if not iid.startswith("dlg-"):
                return
            idx = int(iid[4:])
            if idx >= len(self._shown):
                return
            d = self._shown[idx]
            self._active_entity = d.entity
            self._active_id     = d.id
            self._pending_delete = None

            ent   = d.entity
            dname = d.name or "(nomsiz)"
            icon  = _icon(ent)
            col   = _col(ent)
            dt    = _dtype(ent)
            cat   = self._catmgr.get(d.id, dname)

            type_labels = {"user": "Shaxsiy", "bot": "Bot",
                           "group": "Guruh",  "channel": "Kanal"}

            self.query_one("#header-icon", Static).update(f"[bold {col}]{icon}[/]")
            self.query_one("#header-name", Static).update(
                f"[bold white]{escape(dname)}[/]")
            self.query_one("#header-cat", Static).update(
                f"[#ffb700]{escape(cat)}[/]" if cat else "")
            self.query_one("#header-meta", Static).update(
                f"[#3d5570]{type_labels.get(dt, '')}[/]")

            self._unread_ids.discard(d.id)
            try:
                await self.tg.send_read_acknowledge(d.entity)
            except Exception:
                pass

            await self._build_cat_list()
            await self._rebuild_chat_list()
            self._set_status(f"Yuklanmoqda: {dname}…")
            await self._load_history(d.entity)
            self._set_status(f"◉ {dname}  │  Ctrl+G=media  │  /media N")
            self.query_one("#msg-input", Input).focus()

    # ── MEDIA GALLERY ─────────────────────────────────────────────────────
    def action_media_gallery(self) -> None:
        panel = self.query_one("#media-panel")
        if panel.has_class("visible"):
            self._close_media_panel()
        else:
            if self._active_entity is None:
                self.notify("Avval chat tanlang!", severity="warning")
                return
            panel.add_class("visible")
            asyncio.ensure_future(self._build_media_list())

    def _close_media_panel(self) -> None:
        self.query_one("#media-panel").remove_class("visible")
        self.query_one("#msg-input", Input).focus()

    async def _build_media_list(self) -> None:
        lv = self.query_one("#media-list", ListView)
        await lv.clear()
        self._media_messages = []

        if not self._history_messages:
            await lv.append(ListItem(
                Label("[#3d5570]  Media topilmadi[/]"), id="media-empty"))
            return

        for m in self._history_messages:
            if getattr(m, "sticker", None):
                continue
            if not _has_media(m):
                continue

            self._media_messages.append(m)
            idx = len(self._media_messages) - 1

            info  = _media_info(m) or "📎 Media"
            fname = _file_name_str(m)
            size  = _file_size_str(m)
            ts    = _ts(m.date)

            parts = [f"[bold #c084fc]{info}[/]"]
            if fname:
                parts.append(f"[white]{escape(_short(fname, 20))}[/]")
            if size:
                parts.append(f"[#3d5570]{size}[/]")
            parts.append(f"[#3d5570]{ts}[/]")
            parts.append("[#39ff14]↗ ochish[/]")

            label_text = "  ".join(parts)
            await lv.append(ListItem(Label(label_text), id=f"media-{idx}"))

        cnt = len(self._media_messages)
        self._set_status(f"📷 Media: {cnt} ta  (bosing → lokal ochiladi)")
        if cnt > 0:
            try:
                lv.index = 0
            except Exception:
                pass

    # ── MEDIA ochish — HAR QANDAY MEDIA → LOKAL KO'RUVCHI ─────────────────
    @staticmethod
    def _is_termux() -> bool:
        return (
            "TERMUX_VERSION" in os.environ
            or os.environ.get("PREFIX", "").startswith("/data/data/com.termux")
            or os.path.exists("/data/data/com.termux")
        )

    def _has_display(self) -> bool:
        if sys.platform in ("win32", "darwin"):
            return True
        if self._is_termux():
            return True
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    def _open_media(self, path: str) -> None:
        """
        Barcha media (rasm, video, audio) → tashqi ko'ruvchi bilan lokal ochiladi.
        Faqat hujjatlar (PDF, HTML) brauzerda ochiladi.
        """
        if not self._has_display():
            self.notify(
                f"📁 {os.path.abspath(path)}",
                title="GUI yo'q — faylni qo'lda oching",
            )
            return

        ext = os.path.splitext(path)[1].lower()

        if ext in _BROWSER_EXTS:
            # PDF/HTML → brauzer
            self._open_in_browser(path)
        else:
            # Rasm, video, audio → tashqi ko'ruvchi (eog, feh, VLC, va h.k.)
            self._open_with_system(path)

    def _open_with_system(self, path: str) -> None:
        """Barcha media turlarini lokal ko'ruvchida ochish."""
        abs_path = os.path.abspath(path)
        try:
            if sys.platform == "win32":
                # Windows — default dastur bilan ochish
                os.startfile(abs_path)
            elif sys.platform == "darwin":
                # macOS — Preview.app / QuickTime
                subprocess.Popen(["open", abs_path])
            elif self._is_termux():
                # Android (Termux) — Termux:API orqali
                subprocess.Popen(
                    ["termux-open", abs_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # Linux — xdg-open (eog, feh, vlc, va h.k.)
                subprocess.Popen(
                    ["xdg-open", abs_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self.notify(f"▶ Ochildi: {os.path.basename(path)}", title="Lokal")
        except FileNotFoundError:
            self.notify(
                "xdg-open o'rnatilmagan. O'rnating: sudo dnf install xdg-utils",
                title="⚠ Xato", severity="warning",
            )
            self.notify(f"📁 {abs_path}", title="Fayl yo'li")
        except Exception as exc:
            self.notify(f"{exc}", title="⚠ Ochib bo'lmadi", severity="warning")
            self.notify(f"📁 {abs_path}", title="Fayl yo'li")

    def _open_in_browser(self, path: str) -> None:
        """Faqat hujjatlar (PDF, HTML) uchun — brauzerda ochish."""
        try:
            abs_path = os.path.abspath(path)
            if sys.platform == "win32":
                url = "file:///" + abs_path.replace("\\", "/")
            else:
                url = "file://" + abs_path
            webbrowser.open(url)
            self.notify(f"Brauzerda ochildi: {os.path.basename(path)}", title="📄")
        except Exception:
            self._open_with_system(path)

    async def _download_media(self, message) -> Optional[str]:
        total_size = 0
        try:
            total_size = message.file.size or 0
        except Exception:
            pass

        if total_size > 200 * 1024 * 1024:
            self.notify(
                "Fayl 200 MB dan katta. Yuklab olish uzoq vaqt olishi mumkin.",
                title="⚠ Juda katta fayl", severity="warning",
            )

        def _progress(current: int, total: int) -> None:
            if total and total > 0:
                pct = int(current * 100 / total)
                mb  = current / (1024 * 1024)
                tmb = total / (1024 * 1024)
                try:
                    self.query_one("#statusbar", StatusBar).status = (
                        f"⬇ Yuklanmoqda… {pct}%  ({mb:.1f}/{tmb:.1f} MB)"
                    )
                except Exception:
                    pass

        try:
            path = await self.tg.download_media(
                message,
                file=DOWNLOAD_DIR + "/",
                progress_callback=_progress,
            )
            return path
        except Exception as exc:
            self.notify(str(exc), title="✗ Yuklab olinmadi", severity="error")
            return None

    async def _view_media_message(self, message) -> None:
        if getattr(message, "sticker", None):
            self.notify("Stikerlar ochilmaydi.", severity="information")
            return
        if not _has_media(message):
            self.notify("Bu xabarda media yo'q.", severity="warning")
            return

        self._set_status("⬇ Media yuklab olinmoqda…")
        path = await self._download_media(message)
        if not path:
            self._set_status("✗ Yuklab olinmadi")
            return

        self._set_status(f"✓ Yuklandi: {os.path.basename(path)}")
        self._open_media(path)

    async def _view_media_at(self, idx: int) -> None:
        if idx < 1 or idx > len(self._history_messages):
            self.notify("Bunday raqamli xabar yo'q.", severity="warning")
            return
        await self._view_media_message(self._history_messages[idx - 1])

    async def _view_last_media(self) -> None:
        for m in reversed(self._history_messages):
            if _has_media(m):
                await self._view_media_message(m)
                return
        self.notify("Bu chatda media topilmadi.", severity="warning")

    async def action_view_media(self) -> None:
        if self._active_entity is None:
            self.notify("Avval chat tanlang!", severity="warning")
            return
        await self._view_last_media()

    # ── GLOBAL qidiruv ────────────────────────────────────────────────────
    async def _global_search(self, query: str) -> list:
        try:
            result = await self.tg(ContactSearchRequest(q=query, limit=20))
            entities = []
            seen_ids: set = set()

            local_ids = set()
            for d in self._all:
                eid = getattr(d.entity, "id", None)
                if eid is not None:
                    local_ids.add(abs(eid))

            for u in getattr(result, "users", []):
                if u.id not in seen_ids and abs(u.id) not in local_ids:
                    entities.append(u)
                    seen_ids.add(u.id)

            for c in getattr(result, "chats", []):
                if c.id not in seen_ids and abs(c.id) not in local_ids:
                    entities.append(c)
                    seen_ids.add(c.id)

            return entities
        except Exception:
            return []

    async def _do_global_search(self, query: str) -> None:
        if not query or len(query) < 2:
            return
        self._set_status(f"🌐 Global qidirilmoqda: '{query}'…")
        results = await self._global_search(query)
        self._global_results = results
        await self._rebuild_chat_list()
        if results:
            self._set_status(f"🌐 '{query}' — {len(results)} ta global natija")
        else:
            self._set_status(f"🌐 '{query}' — global natija topilmadi")

    async def _debounced_global_search(self) -> None:
        await asyncio.sleep(1.2)
        q = self._search_query
        if q and len(q) >= 2:
            await self._do_global_search(q)

    async def _open_global_result(self, entity) -> None:
        try:
            name = _name(entity)
            self._active_entity = entity
            self._active_id = getattr(entity, "id", None)
            self._pending_delete = None

            icon = _icon(entity)
            col  = _col(entity)
            dt   = _dtype(entity)

            self.query_one("#header-icon", Static).update(f"[bold {col}]{icon}[/]")
            self.query_one("#header-name", Static).update(
                f"[bold white]{escape(name)}[/]")
            self.query_one("#header-cat", Static).update("")

            type_labels = {"user": "Shaxsiy", "bot": "Bot",
                           "group": "Guruh",  "channel": "Kanal"}
            self.query_one("#header-meta", Static).update(
                f"[#ff2d78]🌐 {type_labels.get(dt, '')}[/]")

            self._set_status(f"Yuklanmoqda: {name}…")
            await self._load_history(entity)
            self._set_status(f"🌐 {name}  │  Global qidiruv natijasi")
            self.query_one("#msg-input", Input).focus()
        except Exception as exc:
            self.notify(str(exc), title="✗ Xato", severity="error")

    # ── Xabar tarixi (2 bo'sh joy) ────────────────────────────────────────
    def _write_message(self, log: RichLog, ts: str, sender: str,
                       text: str, own: bool, idx: Optional[int] = None,
                       is_media: bool = False) -> None:
        sender_name = sender or "Noma'lum"
        msg_no = f"[#3d5570]{idx:02d}[/] " if idx is not None else ""
        safe_sender = escape(_short(sender_name, 17))
        safe_text = escape(text or "")

        text_col = "#ff2d78" if is_media else ("#ffffff" if own else "#cce8ff")

        if own:
            log.write(
                f"{msg_no}[#1e3a5f]┤[/] [bold #00d4ff]{ts}[/] "
                f"[#00d4ff]SIZ[/]  [{text_col}]{safe_text}[/]")
        else:
            log.write(
                f"{msg_no}[#1e3a5f]│[/] [bold #39ff14]{ts}[/] "
                f"[#39ff14]{safe_sender}[/]  [{text_col}]{safe_text}[/]")

    async def _load_history(self, entity, limit: int = 80) -> None:
        log = self.query_one("#message-log", RichLog)
        log.clear()
        self._history_messages = []

        msgs = []
        async for m in self.tg.iter_messages(entity, limit=limit):
            msgs.append(m)
        msgs.reverse()

        for m in msgs:
            text  = m.text or ""
            media = _media_info(m)

            if not text and not media:
                continue

            self._history_messages.append(m)
            idx = len(self._history_messages)
            ts  = _ts(m.date)

            try:
                s = await m.get_sender()
                sname = _name(s) if s else "Noma'lum"
            except Exception:
                sname = "Noma'lum"

            if media and text:
                display = f"{media}  {text}"
            elif media:
                display = media
            else:
                display = text

            if self._me and m.sender_id == self._me.id:
                self._write_message(log, ts, "SIZ", display,
                                    own=True, idx=idx, is_media=bool(media))
            else:
                self._write_message(log, ts, sname, display,
                                    own=False, idx=idx, is_media=bool(media))

        log.write("[#1e3a5f]" + "─" * 64 + "[/]")
        log.write("[#3d5570]  Ctrl+G=media  │  /media N  │  Ctrl+M=oxirgi media[/]")
        log.scroll_end(animate=False)

        panel = self.query_one("#media-panel")
        if panel.has_class("visible"):
            await self._build_media_list()

    # ── Input submitted ───────────────────────────────────────────────────
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        inp_id = event.input.id or ""

        if inp_id == "search-input":
            query = event.value.strip()
            if query and len(query) >= 2:
                await self._do_global_search(query)
            return

        if inp_id == "cat-input":
            cat_name = event.value.strip()
            if cat_name and self._active_id is not None:
                dname = (self._active_entity and _name(self._active_entity)) or ""
                self._catmgr.assign(self._active_id, cat_name)
                self.query_one("#header-cat", Static).update(
                    f"[#ffb700]{escape(cat_name)}[/]")
                self.notify(f"'{dname}' → '{cat_name}' kategoriyasiga qo'shildi",
                            title="✓ Saqlandi", severity="information")
                await self._build_cat_list()
                await self._rebuild_chat_list()
            self._close_cat_input()
            return

        if inp_id == "msg-input":
            text = event.value.strip()
            if not text:
                return
            if self._active_entity is None:
                self.notify("Avval chat tanlang!", title="⚠", severity="warning")
                return
            event.input.value = ""

            if await self._handle_command(text):
                return

            try:
                sent = await self.tg.send_message(self._active_entity, text)
                self._history_messages.append(sent)
                log = self.query_one("#message-log", RichLog)
                ts  = _ts(datetime.now())
                idx = len(self._history_messages)
                self._write_message(log, ts, "SIZ", text, own=True, idx=idx)
                log.scroll_end(animate=False)
            except Exception as exc:
                self.notify(str(exc), title="✗ Xato", severity="error")

    async def _handle_command(self, text: str) -> bool:
        parts = text.split()
        cmd = parts[0].lower() if parts else ""

        if cmd in {"/media", "/m"}:
            if len(parts) == 2:
                try:
                    idx = int(parts[1])
                    await self._view_media_at(idx)
                except ValueError:
                    self.notify("Ishlatish: /media 5", severity="warning")
            else:
                await self._view_last_media()
            return True

        if cmd not in {"/del", "/delete", "/delchat", "/deletechat", "/leave"}:
            return False

        if cmd in {"/del", "/delete"}:
            if len(parts) > 2:
                self.notify("Ishlatish: /del yoki /del 12", title="Xato", severity="warning")
                return True
            msg_index = None
            if len(parts) == 2:
                try:
                    msg_index = int(parts[1])
                except ValueError:
                    self.notify("Xabar raqami noto'g'ri.", title="Xato", severity="warning")
                    return True
            await self._delete_message_at(msg_index)
            return True

        await self._delete_active_dialog()
        return True

    async def _delete_message_at(self, msg_index: Optional[int] = None) -> None:
        if self._active_entity is None:
            self.notify("Avval chat tanlang!", title="⚠", severity="warning")
            return
        if not self._history_messages:
            self.notify("O'chirish uchun xabar yo'q.", title="⚠", severity="warning")
            return
        if msg_index is None:
            msg_index = len(self._history_messages)
        if msg_index < 1 or msg_index > len(self._history_messages):
            self.notify("Bunday raqamli xabar yo'q.", title="Xato", severity="warning")
            return
        msg = self._history_messages[msg_index - 1]
        try:
            await self.tg.delete_messages(self._active_entity, [msg.id], revoke=True)
            self.notify(f"{msg_index}-xabar o'chirildi.", title="✓")
            await self._load_history(self._active_entity)
            self._pending_delete = None
        except Exception as exc:
            self.notify(str(exc), title="✗ O'chirilmadi", severity="error")

    async def _delete_active_dialog(self) -> None:
        if self._active_entity is None or self._active_id is None:
            self.notify("Avval chat tanlang!", title="⚠", severity="warning")
            return
        name = _name(self._active_entity)
        try:
            await self.tg.delete_dialog(self._active_entity, revoke=False)
            self._catmgr.remove(self._active_id)
            self._unread_ids.discard(self._active_id)
            self._active_entity = None
            self._active_id = None
            self._history_messages = []
            self._pending_delete = None

            self.query_one("#message-log", RichLog).clear()
            self.query_one("#header-icon", Static).update("◌")
            self.query_one("#header-name", Static).update("Chat tanlang…")
            self.query_one("#header-cat", Static).update("")
            self.query_one("#header-meta", Static).update("")
            self._close_media_panel()

            await self._load_all()
            await self._build_cat_list()
            await self._rebuild_chat_list()
            self.notify(f"'{name}' dialogi o'chirildi.", title="✓")
        except Exception as exc:
            self.notify(str(exc), title="✗ O'chirilmadi", severity="error")

    async def action_delete_message(self) -> None:
        if self._active_id is None:
            self.notify("Avval chat tanlang!", severity="warning")
            return
        if self._pending_delete == ("message", self._active_id):
            await self._delete_message_at()
            return
        self._pending_delete = ("message", self._active_id)
        self._set_status("Oxirgi xabarni o'chirish uchun Ctrl+D ni yana bosing.")
        self.notify("Tasdiqlash uchun Ctrl+D ni yana bosing.", title="Xabar o'chirish")

    async def action_delete_dialog(self) -> None:
        if self._active_id is None:
            self.notify("Avval chat tanlang!", severity="warning")
            return
        if self._pending_delete == ("dialog", self._active_id):
            await self._delete_active_dialog()
            return
        self._pending_delete = ("dialog", self._active_id)
        self._set_status("Chatni o'chirish uchun Ctrl+X ni yana bosing.")
        self.notify("Tasdiqlash uchun Ctrl+X ni yana bosing.", title="Chat o'chirish")

    # ── Kategoriya (Ctrl+T) ───────────────────────────────────────────────
    def action_tag_chat(self) -> None:
        if self._active_entity is None:
            self.notify("Avval chat tanlang!", severity="warning")
            return
        area = self.query_one("#cat-input-area")
        area.add_class("visible")
        ci = self.query_one("#cat-input", Input)
        cur = self._catmgr.get(
            self._active_id or 0,
            _name(self._active_entity) if self._active_entity else "")
        ci.value = cur or ""
        ci.focus()
        cats = self._catmgr.all_names()
        hint = "  ".join(cats[:4])
        self._set_status(f"Kategoriya: {hint} …  (Esc=bekor)")

    async def action_untag_chat(self) -> None:
        if self._active_id is None:
            return
        self._catmgr.remove(self._active_id)
        self.query_one("#header-cat", Static).update("")
        self.notify("Kategoriya olib tashlandi.", title="✓")
        await self._build_cat_list()
        await self._rebuild_chat_list()

    # ── Escape — barcha overlay'larni yopish ──────────────────────────────
    def action_close_overlays(self) -> None:
        media_panel = self.query_one("#media-panel")
        if media_panel.has_class("visible"):
            self._close_media_panel()
            return
        search_area = self.query_one("#search-area")
        if search_area.has_class("visible"):
            self._close_search()
            return
        self._close_cat_input()

    def _close_cat_input(self) -> None:
        self.query_one("#cat-input-area").remove_class("visible")
        self.query_one("#cat-input", Input).value = ""
        self.query_one("#msg-input", Input).focus()
        self._set_status(
            f"◉ {_name(self._active_entity) if self._active_entity else '—'}")

    # ── Qidiruv (Ctrl+F / tugma) ──────────────────────────────────────────
    def action_search(self) -> None:
        area = self.query_one("#search-area")
        if area.has_class("visible"):
            self._close_search()
        else:
            area.add_class("visible")
            si = self.query_one("#search-input", Input)
            si.value = ""
            si.focus()
            self._set_status("🔍 Qidiruv… (Enter=global, Esc=yopish)")

    def _close_search(self) -> None:
        self.query_one("#search-area").remove_class("visible")
        self.query_one("#search-input", Input).value = ""
        self._search_query = ""
        self._global_results = []
        if self._search_debounce_task:
            self._search_debounce_task.cancel()
            self._search_debounce_task = None
        self.query_one("#msg-input", Input).focus()
        asyncio.ensure_future(self._rebuild_chat_list())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-search":
            self.action_search()
        elif event.button.id == "btn-media-gallery":
            self.action_media_gallery()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._search_query = event.value.strip().lower()
            self._global_results = []
            await self._rebuild_chat_list()

            if self._search_debounce_task:
                self._search_debounce_task.cancel()
                self._search_debounce_task = None
            if self._search_query and len(self._search_query) >= 2:
                self._search_debounce_task = asyncio.create_task(
                    self._debounced_global_search())

    # ── Yangilash ─────────────────────────────────────────────────────────
    async def action_reload(self) -> None:
        self._set_status("Yangilanmoqda…")
        await self._load_all()
        await self._build_cat_list()
        await self._rebuild_chat_list()

    # ── Real-time ─────────────────────────────────────────────────────────
    def _register_handlers(self) -> None:
        tg  = self.tg
        app = self

        @tg.on(events.NewMessage)
        async def _new(event):
            peer   = event.chat_id
            active = app._active_id

            if active is None or (peer != active and abs(peer) != abs(active)):
                for d in app._all:
                    if d.id == peer or abs(d.id) == abs(peer):
                        app._unread_ids.add(d.id)
                        break
                await app._build_cat_list()
                await app._rebuild_chat_list()
                return

            text  = event.message.text or ""
            media = _media_info(event.message)
            if not text and not media:
                return

            try:
                s = await event.get_sender()
                sname = _name(s) if s else "Noma'lum"
            except Exception:
                sname = "Noma'lum"

            ts  = _ts(event.message.date)
            log = app.query_one("#message-log", RichLog)
            app._history_messages.append(event.message)
            idx = len(app._history_messages)

            if media and text:
                display = f"{media}  {text}"
            elif media:
                display = media
            else:
                display = text

            if s and app._me and s.id == app._me.id:
                app._write_message(log, ts, "SIZ", display,
                                   own=True, idx=idx, is_media=bool(media))
            else:
                app._write_message(log, ts, sname, display,
                                   own=False, idx=idx, is_media=bool(media))
            log.scroll_end(animate=False)

            panel = app.query_one("#media-panel")
            if panel.has_class("visible") and media:
                await app._build_media_list()

    # ── Yordamchi ─────────────────────────────────────────────────────────
    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#statusbar", StatusBar).status = msg
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Login
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def authenticate(client: TelegramClient) -> None:
    await client.connect()
    if await client.is_user_authorized():
        return

    print("\n╔══════════════════════════════════════╗")
    print("║       SAMANDARGRAM  —  LOGIN         ║")
    print("╚══════════════════════════════════════╝")

    phone = input("  Telefon raqam (+998…):  ").strip()
    await client.send_code_request(phone)
    code = input("  SMS kod            :  ").strip()

    try:
        await client.sign_in(phone, code)
    except errors.SessionPasswordNeededError:
        import getpass
        pwd = getpass.getpass("  2FA paroli         :  ")
        await client.sign_in(password=pwd)

    print("  ✓ Muvaffaqiyatli kirildi!\n")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Entry point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def main() -> None:
    if API_ID == 0 or not API_HASH:
        print("XATO: API_ID va API_HASH ni to'ldiring.")
        print("      https://my.telegram.org → 'API development tools'")
        return

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await authenticate(client)

    app = TelegramTUI(client)
    try:
        await app.run_async()
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
