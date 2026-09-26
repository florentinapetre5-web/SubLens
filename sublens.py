#!/usr/bin/env python3
"""
SubLens - Live game subtitle/dialog translator (PySide6)

Features:
  - Fast multi-monitor capture via mss (Pillow fallback)
  - LRU translation cache (200 entries)
  - Unicode emoji/symbol filter (icons aren't mistaken for text)
  - "Stroke" subtitle mode: for outlined game subtitles (RDR2/SM2)
  - Advanced adaptive thresholding (bright/complex backgrounds)
  - Fast subtitle mode: short interval + hash-based change detection
  - Minimal draggable overlay
  - Global hotkeys (F2/F3/F4 + Ctrl+Alt+R/T/G/H) - works while game is fullscreen
  - Auto-pause: scanning pauses when the game window loses focus
  - Glossary: protects proper names and terms from translation
  - Automatic mode detection (tries 6 OCR modes and picks the best)
  - Minimize to system tray
"""

from __future__ import annotations

import sys
import os
import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
import re
import hashlib
import difflib
import unicodedata
import shutil
from collections import OrderedDict
from pathlib import Path

from PIL import (
    Image, ImageGrab, ImageEnhance, ImageFilter, ImageStat, ImageChops, ImageOps
)
import pytesseract

try:
    import mss  # fast screen capture
    HAS_MSS = True
except Exception:
    HAS_MSS = False

try:
    import keyboard  # global hotkey
    HAS_KEYBOARD = True
except Exception:
    HAS_KEYBOARD = False

try:
    import win32gui
    import win32process
    HAS_WIN32 = True
except Exception:
    HAS_WIN32 = False

from PySide6.QtCore import Qt, QObject, Signal, QRect, QPoint, QTimer, QSize, QEvent, QUrl
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPixmap, QImage, QShortcut,
    QKeySequence, QGuiApplication, QCursor, QFontMetrics, QClipboard, QIcon,
    QTextCursor, QPalette, QAction, QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QComboBox,
    QLineEdit, QCheckBox, QRadioButton, QDoubleSpinBox, QFrame, QHBoxLayout,
    QVBoxLayout, QGridLayout, QDialog, QTextBrowser, QTextEdit, QButtonGroup,
    QSizePolicy, QSplitter, QGraphicsDropShadowEffect, QMessageBox,
    QScrollArea, QToolButton, QSystemTrayIcon, QMenu, QPlainTextEdit,
)


TESSERACT_URL = "https://github.com/UB-Mannheim/tesseract/wiki"


def find_tesseract() -> str | None:
    """Locate the Tesseract binary; return None if not found."""
    # 1) Bundled inside a frozen EXE?
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "tesseract" / "tesseract.exe"
        if bundled.exists():
            tessdata = bundled.parent / "tessdata"
            if tessdata.exists():
                os.environ["TESSDATA_PREFIX"] = str(tessdata)
            return str(bundled)
    # 2) Standard Windows install paths
    for cand in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe"),
    ):
        if cand and Path(cand).exists():
            return cand
    # 3) On PATH
    p = shutil.which("tesseract")
    if p:
        return p
    return None


_tess_path = find_tesseract()
if _tess_path:
    pytesseract.pytesseract.tesseract_cmd = _tess_path


APP_NAME = "SubLens"
APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
LEGACY_CONFIG = Path(os.environ.get("APPDATA") or Path.home()) / "GameTranslator" / "config_qt.json"

OCR_LANG_MAP = {
    "English": "eng", "Turkish": "tur", "Japanese": "jpn",
    "Korean": "kor", "Chinese": "chi_sim", "French": "fra",
    "German": "deu", "Spanish": "spa", "Russian": "rus",
    "Italian": "ita", "Portuguese": "por", "Polish": "pol",
    "Auto-Detect": "eng",
}

LANGS = ["English", "Turkish", "Japanese", "Korean", "Chinese",
         "French", "German", "Spanish", "Russian", "Italian",
         "Portuguese", "Polish", "Auto-Detect"]

PSM_OPTIONS = [
    "6 - Single text block (recommended)",
    "7 - Single line",
    "11 - Sparse text",
    "13 - Raw line",
]

OCR_MODES = [
    ("auto",     "Automatic"),
    ("light",    "Light text / dark background"),
    ("dark",     "Dark text / light background"),
    ("subtitle", "Subtitle (top-hat)"),
    ("stroke",   "Outlined subtitle (RDR2/SM2)"),
    ("equalize", "Complex background (eq)"),
]

# Colors
BG_DARK      = "#0d0f14"
BG_CARD      = "#1a1e2a"
ACCENT       = "#7c6af7"
ACCENT_GLOW  = "#9d8fff"
TEXT_PRIMARY = "#e8e6ff"
TEXT_DIM     = "#7a7993"
SUCCESS      = "#4ecb71"
WARNING      = "#f5a623"
ERROR        = "#f76a6a"
BORDER       = "#252840"

ENGINE_ACCENT = {
    "lmstudio": "#9d8fff",
    "deepl":    "#06c8f0",
    "google":   "#69a8ff",
}


# -----------------------------------------------------------------------------
#  Translation engines (existing logic unchanged)
# -----------------------------------------------------------------------------

class LMStudioEngine:
    name = "LM Studio"; key = "lmstudio"
    note = "Local AI  -  No internet needed  -  Resource heavy"

    def __init__(self):
        self.url = "http://localhost:1234"
        self.model = "local-model"

    def translate(self, text, src, tgt, ctx=""):
        prompt = (
            f"You are a professional game translator. Translate from {src} to {tgt}. "
            f"Keep names, preserve tone. Output ONLY the translation.\n"
            + (f"Context: {ctx}\n" if ctx else "")
            + f"Text: {text}\nTranslation:"
        )
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3, "max_tokens": 500,
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()

    def test(self):
        req = urllib.request.Request(f"{self.url}/v1/models",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            return [m["id"] for m in data.get("data", [])]


class DeepLFreeEngine:
    name = "DeepL Free"; key = "deepl"
    note = "DeepL free API  -  500k characters/month  -  High quality"

    LANG_MAP = {
        "Turkish": "TR", "English": "EN-US", "Japanese": "JA", "Korean": "KO",
        "Chinese": "ZH", "French": "FR", "German": "DE", "Spanish": "ES",
        "Russian": "RU", "Italian": "IT", "Portuguese": "PT-BR", "Polish": "PL",
        "Auto-Detect": None,
    }

    def __init__(self):
        self.api_key = ""

    def _request(self, url, params, timeout=15):
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
        }, method="POST")
        for delay in [1, 3, 7, None]:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 429 and delay is not None:
                    time.sleep(delay); continue
                raise

    def translate(self, text, src, tgt, ctx=""):
        tgt_code = self.LANG_MAP.get(tgt, tgt.upper())
        src_code = self.LANG_MAP.get(src)
        params = {"text": text, "target_lang": tgt_code}
        if src_code:
            params["source_lang"] = src_code[:2]
        data = self._request("https://api-free.deepl.com/v2/translate", params)
        return data["translations"][0]["text"]

    def test(self):
        if not self.api_key:
            raise ValueError("API key is empty")
        u = self._request("https://api-free.deepl.com/v2/usage", {}, timeout=10)
        return f"{u['character_count']:,} / {u['character_limit']:,} characters used"


class GoogleFreeEngine:
    name = "Google Translate"; key = "google"
    note = "Unofficial free API  -  No API key required"

    LANG_MAP = {
        "Turkish": "tr", "English": "en", "Japanese": "ja", "Korean": "ko",
        "Chinese": "zh", "French": "fr", "German": "de", "Spanish": "es",
        "Russian": "ru", "Italian": "it", "Portuguese": "pt", "Polish": "pl",
        "Auto-Detect": "auto",
    }

    def translate(self, text, src, tgt, ctx=""):
        sl = self.LANG_MAP.get(src, "auto")
        tl = self.LANG_MAP.get(tgt, "tr")
        url = ("https://translate.googleapis.com/translate_a/single"
               f"?client=gtx&sl={sl}&tl={tl}&dt=t&q={urllib.parse.quote(text)}")
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/124.0 Safari/537.36")})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
            return "".join(seg[0] for seg in data[0] if seg[0])

    def test(self):
        result = self.translate("Hello world", "English", "Turkish")
        if not result:
            raise ValueError("Empty response")
        return f"'Hello world' -> '{result}'"


# -----------------------------------------------------------------------------
#  Screen capture (mss preferred, Pillow fallback)
# -----------------------------------------------------------------------------

class Grabber:
    """Thread-safe screen grabber. mss needs a separate instance per thread."""
    def __init__(self):
        self._local = threading.local()

    def _sct(self):
        s = getattr(self._local, "sct", None)
        if s is None and HAS_MSS:
            # mss >=10: mss.MSS, older: mss.mss
            ctor = getattr(mss, "MSS", None) or mss.mss
            s = ctor()
            self._local.sct = s
        return s

    def grab(self, region):
        x1, y1, x2, y2 = region
        if HAS_MSS:
            try:
                sct = self._sct()
                shot = sct.grab({"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1})
                return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            except Exception:
                pass
        try:
            return ImageGrab.grab(bbox=region, all_screens=True)
        except TypeError:
            return ImageGrab.grab(bbox=region)


GRABBER = Grabber()


# -----------------------------------------------------------------------------
#  LRU translation cache
# -----------------------------------------------------------------------------

class LRUCache:
    def __init__(self, capacity=200):
        self.cap = capacity
        self.d = OrderedDict()

    def get(self, k):
        if k in self.d:
            self.d.move_to_end(k)
            return self.d[k]
        return None

    def put(self, k, v):
        self.d[k] = v
        self.d.move_to_end(k)
        if len(self.d) > self.cap:
            self.d.popitem(last=False)


# -----------------------------------------------------------------------------
#  OCR helpers
# -----------------------------------------------------------------------------

def otsu_threshold(gray: Image.Image) -> int:
    hist = gray.histogram()
    hist = (hist + [0] * 256)[:256]
    total = sum(hist)
    if total == 0:
        return 128
    sum_total = sum(i * hist[i] for i in range(256))
    sum_b, w_b, max_var, thr = 0, 0, 0.0, 128
    for t in range(256):
        w_b += hist[t]
        w_f = total - w_b
        if w_b == 0 or w_f == 0:
            continue
        sum_b += t * hist[t]
        md = (sum_b / w_b) - ((sum_total - sum_b) / w_f)
        var = w_b * w_f * md * md
        if var > max_var:
            max_var, thr = var, t
    return thr


def preprocess(img: Image.Image, scale: int, mode: str) -> Image.Image:
    w, h = img.size
    img = img.resize((w * scale, h * scale), Image.LANCZOS)
    gray = img.convert("L").filter(ImageFilter.MedianFilter(size=3))

    if mode == "subtitle":
        r = max(10, min(gray.size) // 30)
        bg = gray.filter(ImageFilter.GaussianBlur(radius=r))
        diff = ImageChops.subtract(gray, bg)
        diff = ImageEnhance.Contrast(diff).enhance(2.5)
        binary = diff.point(lambda x: 255 if x < 45 else 0)
        binary = binary.filter(ImageFilter.MaxFilter(3))
        binary = binary.filter(ImageFilter.MinFilter(3))
        return binary

    if mode == "stroke":
        # Outlined game subtitles (RDR2, Spider-Man 2, etc.): bright text +
        # dark outline. First find edges, then "fill" inside the outline.
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edges = ImageEnhance.Contrast(edges).enhance(2.0)
        edge_mask = edges.point(lambda x: 255 if x > 60 else 0)
        edge_mask = edge_mask.filter(ImageFilter.MaxFilter(3))
        # High brightness + proximity to edges = text
        bright = gray.point(lambda x: 255 if x > 180 else 0)
        # Intersect bright region with edge mask
        combined = ImageChops.multiply(bright, edge_mask)
        # Invert for Tesseract: text=0, bg=255
        result = combined.point(lambda x: 0 if x > 80 else 255)
        result = result.filter(ImageFilter.MinFilter(3))
        return result

    if mode == "equalize":
        # Histogram equalization for complex backgrounds
        gray = ImageOps.equalize(gray)
        gray = ImageEnhance.Contrast(gray).enhance(1.8)
        avg = ImageStat.Stat(gray).mean[0]
        if avg < 128:
            gray = gray.point(lambda x: 255 - x)
        t = otsu_threshold(gray)
        return gray.point(lambda x: 0 if x < t else 255)

    # auto / light / dark
    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    if mode == "auto":
        invert = ImageStat.Stat(gray).mean[0] < 128
    elif mode == "light":
        invert = True
    else:
        invert = False
    if invert:
        gray = gray.point(lambda x: 255 - x)
    t = otsu_threshold(gray)
    return gray.point(lambda x: 0 if x < t else 255)


def is_noise_word(word: str) -> bool:
    """Is this an emoji/icon/symbol leftover?"""
    if not word:
        return True
    letters = sum(1 for c in word if c.isalpha())
    digits = sum(1 for c in word if c.isdigit())
    # Pure symbol / emoji
    if letters == 0 and digits == 0:
        return True
    # Drop if symbol category (So = Symbol, other) density is high
    sym = sum(1 for c in word if unicodedata.category(c).startswith(("So", "Sk")))
    if sym >= max(1, len(word) // 3):
        return True
    # Single character and not a letter
    if len(word) == 1 and not word.isalpha():
        return True
    return False


def strip_emoji(s: str) -> str:
    return "".join(c for c in s if not unicodedata.category(c).startswith(("So", "Sk", "Cn", "Co")))


# -----------------------------------------------------------------------------
#  Glossary (term protection) - pre-protect / post-restore
# -----------------------------------------------------------------------------

def parse_glossary(text: str) -> list[tuple[str, str]]:
    """Each line is 'source=target' or just 'source' (do not translate). '#' is a comment."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            src, tgt = line.split("=", 1)
            src, tgt = src.strip(), tgt.strip()
        else:
            src, tgt = line, line
        if src:
            out.append((src, tgt))
    # Match longer terms first (avoid substring conflicts)
    out.sort(key=lambda kv: -len(kv[0]))
    return out


def protect_terms(text: str, glossary: list[tuple[str, str]]) -> tuple[str, dict[str, str]]:
    """Replace glossary terms with sentinels; return a placeholder->target map."""
    if not glossary:
        return text, {}
    placeholders: dict[str, str] = {}
    out = text
    for i, (src, tgt) in enumerate(glossary):
        token = f"⁣GT{i}⁣"  # invisible separator, preserved by most engines
        pattern = re.compile(rf"(?i)\b{re.escape(src)}\b")
        if pattern.search(out):
            out = pattern.sub(token, out)
            placeholders[token] = tgt
    return out, placeholders


def restore_terms(text: str, placeholders: dict[str, str]) -> str:
    for token, tgt in placeholders.items():
        text = text.replace(token, tgt)
    # If the engine partially swallowed the sentinel, also match the bare 'GT3' pattern
    def _fallback(m):
        idx = m.group(1)
        for tok, tgt in placeholders.items():
            if tok.strip("⁣") == f"GT{idx}":
                return tgt
        return m.group(0)
    text = re.sub(r"\bGT(\d+)\b", _fallback, text)
    return text


# -----------------------------------------------------------------------------
#  Win32 helpers
# -----------------------------------------------------------------------------

def get_foreground_info() -> tuple[int, int, str]:
    """Active window (hwnd, pid, title). Returns (0,0,'') if win32 is missing."""
    if not HAS_WIN32:
        return 0, 0, ""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        title = win32gui.GetWindowText(hwnd) or ""
        return hwnd, pid, title
    except Exception:
        return 0, 0, ""


# -----------------------------------------------------------------------------
#  Tray icon (no asset required, drawn at runtime)
# -----------------------------------------------------------------------------

def make_tray_icon(active: bool = False) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QColor(SUCCESS if active else ACCENT)
    p.setBrush(QBrush(bg))
    p.setPen(QPen(QColor(BG_DARK), 2))
    p.drawRoundedRect(2, 2, 28, 28, 7, 7)
    p.setPen(QPen(QColor(BG_DARK)))
    p.setFont(QFont("Segoe UI", 14, QFont.Black))
    p.drawText(pm.rect(), Qt.AlignCenter, "S")
    p.end()
    return QIcon(pm)


# -----------------------------------------------------------------------------
#  Region Selector
# -----------------------------------------------------------------------------

class RegionSelector(QWidget):
    selected = Signal(tuple)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        # Cover the entire virtual desktop
        geo = QRect()
        for scr in QGuiApplication.screens():
            geo = geo.united(scr.geometry())
        self.setGeometry(geo)
        self._origin_screen = geo.topLeft()
        self._start = None
        self._end = None
        self._dragging = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        # Top text
        p.setFont(QFont("Segoe UI", 14, QFont.Bold))
        p.setPen(QColor(ACCENT_GLOW))
        p.drawText(self.rect().adjusted(0, 30, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                   "Select the dialog box   ·   ESC = Cancel")
        if self._start and self._end:
            r = QRect(self._start, self._end).normalized()
            # Clear the selection area
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(QColor(ACCENT_GLOW), 2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            # Size label
            p.setFont(QFont("Consolas", 10, QFont.Bold))
            p.setPen(QColor(TEXT_PRIMARY))
            p.drawText(r.adjusted(6, -22, 0, 0), Qt.AlignLeft | Qt.AlignTop,
                       f"{r.width()} × {r.height()}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start = e.position().toPoint()
            self._end = self._start
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._end = e.position().toPoint()
        r = QRect(self._start, self._end).normalized()
        if r.width() < 20 or r.height() < 10:
            self.close()
            return
        ox, oy = self._origin_screen.x(), self._origin_screen.y()
        self.selected.emit((r.left() + ox, r.top() + oy,
                            r.right() + ox, r.bottom() + oy))
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()


# -----------------------------------------------------------------------------
#  Overlay
# -----------------------------------------------------------------------------

class OverlayWindow(QWidget):
    def __init__(self, engine_key="google"):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.engine_key = engine_key
        self._drag_pos = None

        accent = ENGINE_ACCENT.get(engine_key, ACCENT)

        # Rounded-corner card
        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card.setStyleSheet(f"""
            QFrame#card {{
                background: rgba(13, 15, 20, 230);
                border: 1px solid {accent};
                border-radius: 10px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.card.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.addWidget(self.card)

        v = QHBoxLayout(self.card)
        v.setContentsMargins(14, 10, 10, 10)
        v.setSpacing(6)

        self.lbl = QLabel("...")
        self.lbl.setWordWrap(True)
        self.lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; background: transparent; "
            f"font: 25pt 'Segoe UI';")
        self.lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.lbl, 1)

        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QToolButton {{ color: {TEXT_DIM}; background: transparent; "
            f"border: none; font: bold 11pt; padding: 0 4px; }} "
            f"QToolButton:hover {{ color: {ERROR}; }}")
        close_btn.clicked.connect(self.hide)
        v.addWidget(close_btn, 0, Qt.AlignTop)

        self.resize(480, 90)

    def set_engine(self, key: str):
        self.engine_key = key
        accent = ENGINE_ACCENT.get(key, ACCENT)
        self.card.setStyleSheet(f"""
            QFrame#card {{
                background: rgba(13, 15, 20, 230);
                border: 1px solid {accent};
                border-radius: 10px;
            }}
        """)

    def set_text(self, text: str, region=None):
        self.lbl.setText(text)
        scr = QGuiApplication.primaryScreen().virtualGeometry()
        if region:
            w = max(420, min(region[2] - region[0] + 40, scr.width() - 40))
        else:
            w = self.width()
        self.lbl.setFixedWidth(w - 80)
        h_lbl = self.lbl.sizeHint().height()
        h = h_lbl + 48
        if region:
            rx1, ry1, rx2, _ = region
            x = max(scr.left(), min(rx1 - 10, scr.right() - w))
            y = ry1 - h - 8
            if y < scr.top():
                y = region[3] + 8
            y = max(scr.top(), min(y, scr.bottom() - h - 4))
        else:
            x, y = self.x(), self.y()
        self.setGeometry(x, y, w, h)
        self.show()
        self.raise_()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _):
        self._drag_pos = None


# -----------------------------------------------------------------------------
#  Bridge (thread -> UI signals)
# -----------------------------------------------------------------------------

class Bridge(QObject):
    log = Signal(str, str)
    result = Signal(str)
    status = Signal(str, str)
    preview = Signal(QPixmap)
    models = Signal(list)
    show_overlay = Signal(str)
    # Fired from global hotkeys (kbd thread -> UI thread)
    trigger_pick = Signal()
    trigger_once = Signal()
    trigger_toggle = Signal()
    trigger_hide_overlay = Signal()


# -----------------------------------------------------------------------------
#  Main Window
# -----------------------------------------------------------------------------

class MainWindow(QMainWindow):

    ENGINES = {
        "lmstudio": LMStudioEngine(),
        "deepl":    DeepLFreeEngine(),
        "google":   GoogleFreeEngine(),
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SubLens")
        self.resize(620, 720)
        self.setMinimumSize(540, 560)

        cfg = self._load_config()
        self.engine_key = cfg.get("engine_key", "google")
        self.region = tuple(cfg["region"]) if isinstance(cfg.get("region"), list) and len(cfg["region"]) == 4 else None
        self.lm_url = cfg.get("lm_url", "http://localhost:1234")
        self.lm_model = cfg.get("lm_model", "local-model")
        self.deepl_key = cfg.get("deepl_key", "")
        self.ctx = cfg.get("ctx", "")
        self.interval = float(cfg.get("interval", 1.5))
        self.show_overlay_opt = bool(cfg.get("show_overlay", True))
        self.ocr_scale = int(cfg.get("ocr_scale", 3))
        self.ocr_mode = cfg.get("ocr_mode", "auto")
        self.ocr_psm = cfg.get("ocr_psm", PSM_OPTIONS[0])
        if self.ocr_psm not in PSM_OPTIONS:
            self.ocr_psm = PSM_OPTIONS[0]
        self.src_lang = cfg.get("src_lang", "English")
        self.tgt_lang = cfg.get("tgt_lang", "Turkish")
        self.fast_mode = bool(cfg.get("fast_mode", False))
        # New features
        self.global_hotkeys_on = bool(cfg.get("global_hotkeys", HAS_KEYBOARD))
        self.auto_pause_on = bool(cfg.get("auto_pause", HAS_WIN32))
        self.minimize_to_tray = bool(cfg.get("minimize_to_tray", True))
        self.glossary_text = cfg.get("glossary", "")
        self.glossary = parse_glossary(self.glossary_text)

        self.running = False
        self._paused = False  # auto-pause state (thread keeps running, OCR is skipped)
        self._stop_evt = threading.Event()
        self.last_text = ""
        self.last_hash = ""
        self.overlay: OverlayWindow | None = None
        self._cache = LRUCache(200)
        self._region_selector: RegionSelector | None = None
        self._target_hwnd = 0  # auto-pause target window
        self._self_pid = os.getpid()
        self._registered_hotkeys: list = []
        self._tray: QSystemTrayIcon | None = None
        self._force_quit = False

        self.bridge = Bridge()
        self.bridge.log.connect(self._append_log)
        self.bridge.status.connect(self._set_status)
        self.bridge.preview.connect(self._set_preview)
        self.bridge.models.connect(self._apply_models)
        self.bridge.show_overlay.connect(self._show_overlay)
        self.bridge.trigger_pick.connect(self._pick_region)
        self.bridge.trigger_once.connect(self._translate_once)
        self.bridge.trigger_toggle.connect(self._toggle_scan)
        self.bridge.trigger_hide_overlay.connect(self._hide_overlay)

        self._build_ui()
        self._apply_style()
        self._switch_engine(self.engine_key)
        self._bind_shortcuts()
        self._update_start_state()

        # Connect the signal after the UI is built
        self.bridge.result.connect(self.result_lbl.setText)

        # Tray
        self._setup_tray()

        # Global hotkeys
        if self.global_hotkeys_on:
            self._register_global_hotkeys()

        # Auto-pause QTimer (every 800 ms)
        self._pause_timer = QTimer(self)
        self._pause_timer.setInterval(800)
        self._pause_timer.timeout.connect(self._check_auto_pause)
        if self.auto_pause_on:
            self._pause_timer.start()

        if self.region:
            self._update_region_label()
            QTimer.singleShot(250, self._refresh_preview)

    # -- Style ---------------------------------------------------------------
    def _apply_style(self):
        self.setStyleSheet(f"""
            QMainWindow, QDialog {{ background: {BG_DARK}; }}
           QWidget {{ color: {TEXT_PRIMARY}; font-family: 'Segoe UI'; font-size: 25pt; }}
            QLabel#title {{ font: bold 20pt 'Segoe UI'; color: {ACCENT}; }}
            QLabel#title2 {{ font: bold 20pt 'Segoe UI'; color: {TEXT_PRIMARY}; }}
            QLabel.section {{ color: {TEXT_DIM}; font: bold 9pt 'Consolas'; letter-spacing: 1px; }}
            QLabel.dim {{ color: {TEXT_DIM}; }}
            QLineEdit, QComboBox, QDoubleSpinBox {{
                background: {BG_CARD}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER};
                border-radius: 6px; padding: 5px 8px; selection-background-color: {ACCENT};
            }}
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {ACCENT};
            }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background: {BG_CARD}; color: {TEXT_PRIMARY};
                selection-background-color: {ACCENT}; border: 1px solid {BORDER};
            }}
            QPushButton {{
                background: {ACCENT}; color: {BG_DARK}; border: none; border-radius: 6px;
                padding: 7px 14px; font: bold 9pt 'Segoe UI';
            }}
            QPushButton:hover {{ background: {ACCENT_GLOW}; }}
            QPushButton:disabled {{ background: {BORDER}; color: {TEXT_DIM}; }}
            QPushButton.secondary {{ background: {BG_CARD}; color: {TEXT_PRIMARY}; }}
            QPushButton.secondary:hover {{ background: {BORDER}; }}
            QPushButton.success {{ background: {SUCCESS}; color: {BG_DARK}; }}
            QPushButton.warning {{ background: {WARNING}; color: {BG_DARK}; }}
            QFrame.sep {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
            QFrame.accentBar {{ background: {ACCENT}; max-height: 2px; min-height: 2px; }}
            QFrame.card {{ background: {BG_CARD}; border-radius: 8px; }}
            QCheckBox, QRadioButton {{ color: {TEXT_DIM}; spacing: 6px; }}
            QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
            QCheckBox::indicator:unchecked, QRadioButton::indicator:unchecked {{
                background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 3px;
            }}
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                background: {ACCENT}; border: 1px solid {ACCENT}; border-radius: 3px;
            }}
            QTextEdit, QTextBrowser {{
                background: {BG_CARD}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER};
                border-radius: 6px; padding: 8px; font-family: 'Consolas'; font-size: 9pt;
            }}
            QScrollBar:vertical {{ background: {BG_DARK}; width: 10px; }}
            QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 20px; }}
            QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)

    # -- UI build ------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        t1 = QLabel("SUB"); t1.setObjectName("title")
        t2 = QLabel("LENS"); t2.setObjectName("title2")
        hdr.addWidget(t1); hdr.addWidget(t2); hdr.addStretch(1)
        self.info_btn = QPushButton("ⓘ  Info")
        self.info_btn.setProperty("class", "secondary"); self.info_btn.setObjectName("infoBtn")
        self.info_btn.setStyleSheet(f"background: {BG_CARD}; color: {TEXT_DIM};")
        self.info_btn.clicked.connect(self._open_info)
        self.settings_btn = QPushButton("⚙  Settings")
        self.settings_btn.setStyleSheet(f"background: {BG_CARD}; color: {TEXT_DIM};")
        self.settings_btn.clicked.connect(self._open_settings)
        hdr.addWidget(self.info_btn); hdr.addWidget(self.settings_btn)
        root.addLayout(hdr)

        bar = QFrame(); bar.setProperty("class", "accentBar")
        bar.setStyleSheet(f"background: {ACCENT}; max-height: 2px;")
        root.addWidget(bar)

        # -- Quick-start card (collapsible) --
        self.help_toggle = QToolButton()
        self.help_toggle.setText("\U0001f4a1  Quick start (show)")
        self.help_toggle.setCursor(Qt.PointingHandCursor)
        self.help_toggle.setStyleSheet(
            f"QToolButton {{ color: {TEXT_DIM}; background: transparent; border: none; "
            f"font: 9pt 'Consolas'; padding: 2px 0; text-align: left; }} "
            f"QToolButton:hover {{ color: {ACCENT_GLOW}; }}")
        self.help_toggle.clicked.connect(self._toggle_help)
        root.addWidget(self.help_toggle)

        self.help_card = QLabel(self._help_text())
        self.help_card.setWordWrap(True)
        self.help_card.setTextFormat(Qt.RichText)
        self.help_card.setStyleSheet(
            f"background: {BG_CARD}; color: {TEXT_PRIMARY}; padding: 10px 14px; "
            f"border-left: 3px solid {ACCENT}; border-radius: 6px; font: 9pt 'Segoe UI';")
        self.help_card.hide()
        root.addWidget(self.help_card)

        # Engine selection
        eng = QHBoxLayout()
        lab = QLabel("Engine:"); lab.setStyleSheet(f"color: {TEXT_DIM};")
        eng.addWidget(lab)
        self.engine_btns = {}
        for key, e in self.ENGINES.items():
            b = QPushButton(e.name)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._switch_engine(k))
            eng.addWidget(b)
            self.engine_btns[key] = b
        eng.addStretch(1)
        root.addLayout(eng)

        self.status_lbl = QLabel(""); self.status_lbl.setStyleSheet(f"color: {TEXT_DIM};")
        root.addWidget(self.status_lbl)

        root.addWidget(self._sep())

        # Language selection
        lang = QHBoxLayout()
        lang.addWidget(self._dim("Language:"))
        self.src_combo = QComboBox(); self.src_combo.addItems(LANGS)
        self.src_combo.setCurrentText(self.src_lang if self.src_lang in LANGS else "English")
        lang.addWidget(self.src_combo)
        arrow = QLabel("→"); arrow.setStyleSheet(f"color: {ACCENT}; font: bold 14pt;")
        lang.addWidget(arrow)
        self.tgt_combo = QComboBox(); self.tgt_combo.addItems(LANGS[:-1])
        self.tgt_combo.setCurrentText(self.tgt_lang if self.tgt_lang in LANGS[:-1] else "Turkish")
        lang.addWidget(self.tgt_combo)
        lang.addStretch(1)
        root.addLayout(lang)

        root.addWidget(self._sep())

        # Region
        reg = QHBoxLayout()
        self.pick_btn = QPushButton("\U0001f4d0  Pick Region (F2)")
        self.pick_btn.clicked.connect(self._pick_region)
        reg.addWidget(self.pick_btn)
        self.auto_mode_btn = QPushButton("✨  Find Mode")
        self.auto_mode_btn.setToolTip(
            "Automatically picks the best OCR mode for the selected region "
            "(tries 6 modes and chooses the one with the highest confidence)")
        self.auto_mode_btn.setStyleSheet(f"background: {BG_CARD}; color: {TEXT_PRIMARY};")
        self.auto_mode_btn.clicked.connect(self._auto_detect_mode)
        reg.addWidget(self.auto_mode_btn)
        self.region_lbl = QLabel("Not selected yet")
        self.region_lbl.setStyleSheet(f"color: {TEXT_DIM};")
        reg.addWidget(self.region_lbl); reg.addStretch(1)
        root.addLayout(reg)

        self.preview = QLabel("Preview will appear here once a region is selected")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(80)
        self.preview.setStyleSheet(
            f"background: {BG_CARD}; color: {TEXT_DIM}; border-radius: 6px; padding: 6px;")
        root.addWidget(self.preview)

        root.addWidget(self._sep())

        # Controls
        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("▶  START (F4)")
        self.start_btn.setProperty("class", "success")
        self.start_btn.setStyleSheet(f"background: {SUCCESS}; color: {BG_DARK};")
        self.start_btn.clicked.connect(self._toggle_scan)
        ctrl.addWidget(self.start_btn)

        once = QPushButton("✦  Once (F3)")
        once.clicked.connect(self._translate_once)
        ctrl.addWidget(once)

        ctrl.addWidget(self._dim("Interval:"))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.3, 15.0); self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setDecimals(1); self.interval_spin.setValue(self.interval)
        self.interval_spin.setFixedWidth(70)
        ctrl.addWidget(self.interval_spin)
        ctrl.addWidget(self._dim("s"))

        self.overlay_cb = QCheckBox("Overlay"); self.overlay_cb.setChecked(self.show_overlay_opt)
        ctrl.addWidget(self.overlay_cb)

        self.fast_cb = QCheckBox("Fast subtitle")
        self.fast_cb.setChecked(self.fast_mode)
        self.fast_cb.setToolTip("0.4 s interval + aggressive change detection (RDR2, SM2)")
        ctrl.addWidget(self.fast_cb)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        root.addWidget(self._sep())

        # Result
        lab2 = QLabel("Last Translation"); lab2.setStyleSheet(f"color: {TEXT_DIM}; font: bold 9pt 'Consolas';")
        root.addWidget(lab2)
        self.result_lbl = QLabel("-")
        self.result_lbl.setWordWrap(True)
        self.result_lbl.setStyleSheet(
            f"background: {BG_CARD}; color: {ACCENT_GLOW}; padding: 10px 12px; "
            f"border-radius: 6px; font: 12pt 'Segoe UI';")
        self.result_lbl.setMinimumHeight(60)
        self.result_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        root.addWidget(self.result_lbl)

        # Log (collapsible)
        log_hdr = QHBoxLayout()
        self.log_arrow = QToolButton()
        self.log_arrow.setText("▶  Log")
        self.log_arrow.setStyleSheet(
            f"QToolButton {{ color: {TEXT_DIM}; background: transparent; border: none; "
            f"font: bold 9pt 'Consolas'; }} QToolButton:hover {{ color: {TEXT_PRIMARY}; }}")
        self.log_arrow.setCursor(Qt.PointingHandCursor)
        self.log_arrow.clicked.connect(self._toggle_log)
        log_hdr.addWidget(self.log_arrow); log_hdr.addStretch(1)
        root.addLayout(log_hdr)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(120)
        self.log_box.hide()
        root.addWidget(self.log_box, 1)

    def _sep(self):
        f = QFrame()
        f.setStyleSheet(f"background: {BORDER}; max-height: 1px; min-height: 1px;")
        return f

    def _dim(self, text):
        l = QLabel(text); l.setStyleSheet(f"color: {TEXT_DIM};")
        return l

    def _toggle_log(self):
        if self.log_box.isVisible():
            self.log_box.hide()
            self.log_arrow.setText("▶  Log")
        else:
            self.log_box.show()
            self.log_arrow.setText("▼  Log")

    # -- Shortcuts -----------------------------------------------------------
    def _bind_shortcuts(self):
        QShortcut(QKeySequence("F2"), self, activated=self._pick_region)
        QShortcut(QKeySequence("F3"), self, activated=self._translate_once)
        QShortcut(QKeySequence("F4"), self, activated=self._toggle_scan)
        QShortcut(QKeySequence("Escape"), self, activated=self._hide_overlay)

    def _hide_overlay(self):
        if self.overlay and self.overlay.isVisible():
            self.overlay.hide()

    # -- Config --------------------------------------------------------------
    def _load_config(self):
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        # Migrate old Game Translator (Qt) settings
        if LEGACY_CONFIG.exists():
            try:
                data = json.loads(LEGACY_CONFIG.read_text(encoding="utf-8"))
                CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                CONFIG_PATH.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return data
            except Exception:
                pass
        return {}

    def _save_config(self):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "engine_key": self.engine_key,
                "lm_url": self.lm_url, "lm_model": self.lm_model,
                "deepl_key": self.deepl_key, "ctx": self.ctx,
                "interval": float(self.interval_spin.value()),
                "show_overlay": bool(self.overlay_cb.isChecked()),
                "fast_mode": bool(self.fast_cb.isChecked()),
                "ocr_scale": int(self.ocr_scale), "ocr_mode": self.ocr_mode,
                "ocr_psm": self.ocr_psm,
                "src_lang": self.src_combo.currentText(),
                "tgt_lang": self.tgt_combo.currentText(),
                "region": list(self.region) if self.region else None,
                "global_hotkeys": bool(self.global_hotkeys_on),
                "auto_pause": bool(self.auto_pause_on),
                "minimize_to_tray": bool(self.minimize_to_tray),
                "glossary": self.glossary_text,
            }
            CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def closeEvent(self, e):
        # Minimize to tray: pressing X hides the app, use tray menu to QUIT
        if (self._tray and self._tray.isVisible()
                and self.minimize_to_tray and not self._force_quit):
            e.ignore()
            self.hide()
            self._tray.showMessage(
                "SubLens",
                "Minimized to tray  ·  Use the tray menu to quit",
                QSystemTrayIcon.Information, 2500)
            return
        # Real exit
        self.running = False
        self._paused = False
        self._stop_evt.set()
        if hasattr(self, "_pause_timer"):
            self._pause_timer.stop()
        self._unregister_global_hotkeys()
        # The keyboard library spawns a non-daemon listener thread;
        # if we don't clean up all hooks, the process hangs.
        if HAS_KEYBOARD:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        self._save_config()
        if self.overlay:
            self.overlay.close()
        if self._tray:
            self._tray.hide()
            self._tray = None
        super().closeEvent(e)
        # With setQuitOnLastWindowClosed(False), the event loop won't end on
        # its own - explicit quit + safety-net os._exit
        QApplication.instance().quit()
        QTimer.singleShot(800, lambda: os._exit(0))

    # -- Engine switch -------------------------------------------------------
    def _switch_engine(self, key):
        prev = self.engine_key
        self.engine_key = key
        for k, b in self.engine_btns.items():
            if k == key:
                b.setStyleSheet(
                    f"background: {ENGINE_ACCENT[k]}; color: {BG_DARK}; "
                    f"font: bold 9pt; padding: 7px 14px; border-radius: 6px; border: none;")
            else:
                b.setStyleSheet(
                    f"background: {BG_CARD}; color: {TEXT_DIM}; "
                    f"font: bold 9pt; padding: 7px 14px; border-radius: 6px; border: none;")
        self.status_lbl.setText("")
        if prev != key and self.overlay:
            self.overlay.set_engine(key)

    def _update_start_state(self):
        self.start_btn.setEnabled(self.region is not None)

    def _update_region_label(self):
        r = self.region
        self.region_lbl.setText(
            f"({r[0]},{r[1]}) → ({r[2]},{r[3]})  [{r[2]-r[0]}×{r[3]-r[1]} px]")
        self.region_lbl.setStyleSheet(f"color: {SUCCESS};")

    # -- Signal receivers ----------------------------------------------------
    def _append_log(self, msg, tag):
        colors = {"ok": SUCCESS, "warn": WARNING, "err": ERROR,
                  "tr": ACCENT_GLOW, "dim": TEXT_DIM}
        col = colors.get(tag, TEXT_PRIMARY)
        ts = time.strftime("%H:%M:%S")
        self.log_box.append(
            f'<span style="color:{TEXT_DIM};">[{ts}]</span> '
            f'<span style="color:{col};">{self._html_escape(msg)}</span>')

    @staticmethod
    def _html_escape(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def _set_status(self, text, color):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {color};")

    def _set_preview(self, pm: QPixmap):
        self.preview.setPixmap(pm.scaled(
            self.preview.width(), 100,
            Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _apply_models(self, models):
        # If the combobox is active in the Settings window, populate it
        cb = getattr(self, "lm_combo", None)
        if cb is None:
            return
        try:
            cb.clear()
            cb.addItems(models)
            if models:
                cb.setCurrentText(models[0])
                self.lm_model = models[0]
        except RuntimeError:
            # Settings window was closed -> widget is gone
            self.lm_combo = None

    # -- Region selection ----------------------------------------------------
    def _pick_region(self):
        if self._region_selector and self._region_selector.isVisible():
            return
        self.showMinimized()
        QTimer.singleShot(300, self._open_region_selector)

    def _open_region_selector(self):
        self._region_selector = RegionSelector()
        self._region_selector.selected.connect(self._on_region)
        self._region_selector.destroyed.connect(lambda: self.showNormal())
        self._region_selector.show()
        self._region_selector.activateWindow()
        self._region_selector.setFocus()

    def _on_region(self, r):
        self.region = r
        self._update_region_label()
        self._append_log(f"Region: {r}", "ok")
        self._refresh_preview()
        self._update_start_state()

    def _refresh_preview(self):
        if not self.region:
            return
        try:
            img = GRABBER.grab(self.region)
            img.thumbnail((640, 100))
            qim = self._pil_to_qpixmap(img)
            self.preview.setPixmap(qim)
            self.preview.setText("")
        except Exception as e:
            self._append_log(f"Preview error: {e}", "warn")

    @staticmethod
    def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qim = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qim.copy())

    # -- Single translation --------------------------------------------------
    def _translate_once(self):
        if not self.region:
            QMessageBox.warning(self, "Warning", "Pick a region first!")
            return
        threading.Thread(target=self._do_once, daemon=True).start()

    def _do_once(self):
        self.bridge.log.emit("Reading screen...", "dim")
        text = self._ocr()
        if not text:
            self.bridge.log.emit("No text found.", "warn")
            return
        self.bridge.log.emit(f"OCR -> {text[:70]}{'...' if len(text) > 70 else ''}", "dim")
        try:
            tr = self._translate(text)
            self.bridge.result.emit(tr)
            self.bridge.log.emit(f"> {tr}", "tr")
            if self.overlay_cb.isChecked():
                self.bridge.show_overlay.emit(tr)
        except Exception as e:
            self.bridge.log.emit(f"Translation error: {e}", "err")

    # -- Scan loop -----------------------------------------------------------
    def _toggle_scan(self):
        if self.running:
            self.running = False
            self._paused = False
            self._stop_evt.set()
            self.start_btn.setText("▶  START (F4)")
            self.start_btn.setStyleSheet(f"background: {SUCCESS}; color: {BG_DARK};")
            self._append_log("Scanning stopped.", "warn")
            if self._tray:
                self._tray.setIcon(make_tray_icon(False))
        else:
            if not self.region:
                QMessageBox.warning(self, "Warning", "Pick a region first!")
                return
            self.running = True
            self._paused = False
            self._stop_evt.clear()
            self.last_text = ""
            self.last_hash = ""
            self.start_btn.setText("■  STOP (F4)")
            self.start_btn.setStyleSheet(f"background: {WARNING}; color: {BG_DARK};")

            # Auto-pause target window: if the active window is not ours, target it
            self._target_hwnd = 0
            if self.auto_pause_on and HAS_WIN32:
                hwnd, pid, title = get_foreground_info()
                if pid and pid != self._self_pid:
                    self._target_hwnd = hwnd
                    self._append_log(f"Auto-pause target: {title[:40] or '(untitled)'}", "dim")
                else:
                    self._append_log(
                        "Auto-pause: the first Alt-Tab will set the game window as target", "dim")

            self._append_log(
                f"Scanning started  ·  {self.ENGINES[self.engine_key].name}", "ok")
            if self._tray:
                self._tray.setIcon(make_tray_icon(True))
            threading.Thread(target=self._scan_loop, daemon=True).start()

    def _scan_loop(self):
        while self.running:
            if self._paused:
                if self._stop_evt.wait(0.5):
                    break
                continue
            text = self._ocr()
            if text:
                # Fast early-out via a normalized hash
                norm = re.sub(r"\W+", "", text.lower())
                h = hashlib.md5(norm.encode("utf-8")).hexdigest()[:12]
                fast = self.fast_cb.isChecked()
                ratio = (difflib.SequenceMatcher(None, self.last_text, text).ratio()
                         if self.last_text else 0.0)
                threshold = 0.85 if fast else 0.92
                changed = (h != self.last_hash) and (not self.last_text or ratio < threshold)
                if changed:
                    self.last_text = text
                    self.last_hash = h
                    self.bridge.log.emit(
                        f"New -> {text[:55]}{'...' if len(text) > 55 else ''}", "dim")
                    try:
                        tr = self._translate(text)
                        self.bridge.result.emit(tr)
                        self.bridge.log.emit(f"> {tr}", "tr")
                        if self.overlay_cb.isChecked():
                            self.bridge.show_overlay.emit(tr)
                    except Exception as e:
                        self.bridge.log.emit(f"Error: {e}", "err")
            try:
                base = float(self.interval_spin.value())
            except Exception:
                base = 1.5
            wait = 0.4 if self.fast_cb.isChecked() else base
            if self._stop_evt.wait(max(0.1, wait)):
                break

    # -- Translation (cached + glossary) -------------------------------------
    def _translate(self, text):
        cache_key = f"{self.engine_key}|{self.src_combo.currentText()}|{self.tgt_combo.currentText()}|{text}"
        hit = self._cache.get(cache_key)
        if hit is not None:
            return hit
        eng = self.ENGINES[self.engine_key]
        if self.engine_key == "lmstudio":
            eng.url = self.lm_url
            eng.model = self.lm_model
        elif self.engine_key == "deepl":
            eng.api_key = self.deepl_key

        # Glossary: protect terms with sentinels
        protected, placeholders = protect_terms(text, self.glossary)
        out = eng.translate(protected, self.src_combo.currentText(),
                            self.tgt_combo.currentText(), self.ctx)
        out = restore_terms(out, placeholders)

        self._cache.put(cache_key, out)
        return out

    # -- OCR -----------------------------------------------------------------
    def _ocr(self) -> str:
        if not self.region:
            return ""
        try:
            raw = GRABBER.grab(self.region)
        except Exception as e:
            self.bridge.log.emit(f"Screen capture failed: {e}", "err")
            return ""

        proc = preprocess(raw, self.ocr_scale, self.ocr_mode)
        psm_val = self.ocr_psm.split(" ")[0]
        # tessedit_char_blacklist: block common icon characters
        config = (f"--oem 3 --psm {psm_val} -c preserve_interword_spaces=1 "
                  f"-c tessedit_char_blacklist=©®™€¥§¶•")
        lang = OCR_LANG_MAP.get(self.src_combo.currentText(), "eng")

        try:
            data = pytesseract.image_to_data(
                proc, lang=lang, config=config,
                output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractError as e:
            es = str(e).lower()
            if lang != "eng" and any(s in es for s in ("language", "not loaded", "failed loading", "data file")):
                self.bridge.log.emit(
                    f"Tesseract language pack '{lang}' not found, falling back to eng", "warn")
                data = pytesseract.image_to_data(
                    proc, lang="eng", config=config,
                    output_type=pytesseract.Output.DICT)
            else:
                raise

        words = []
        n = len(data.get("text", []))
        for i in range(n):
            word = strip_emoji((data["text"][i] or "").strip())
            if not word or is_noise_word(word):
                continue
            try:
                conf = int(float(data["conf"][i]))
            except (ValueError, TypeError):
                conf = -1
            if conf < 55:
                continue
            words.append({
                "text": word,
                "left": int(data["left"][i]), "top": int(data["top"][i]),
                "w": int(data["width"][i]), "h": int(data["height"][i]),
            })

        if not words:
            return ""

        heights = sorted(w["h"] for w in words)
        median_h = heights[len(heights) // 2] or 1
        words = [w for w in words if 0.45 * median_h <= w["h"] <= 1.9 * median_h]
        if not words:
            return ""

        y_tol = max(4, median_h // 2)
        words.sort(key=lambda w: (w["top"], w["left"]))
        lines, current, current_y = [], [], None
        for w in words:
            cy = w["top"] + w["h"] / 2
            if current_y is None or abs(cy - current_y) <= y_tol:
                current.append(w)
                current_y = sum(x["top"] + x["h"] / 2 for x in current) / len(current)
            else:
                lines.append(current)
                current, current_y = [w], cy
        if current:
            lines.append(current)

        out = []
        for line in lines:
            line.sort(key=lambda w: w["left"])
            text = " ".join(w["text"] for w in line)
            text = re.sub(r"[\x00-\x1F\x7F]+", " ", text)
            text = re.sub(r"[ \t]+", " ", text).strip()
            alpha = sum(1 for c in text if c.isalpha())
            if alpha < 3:
                continue
            out.append(text)
        return "\n".join(out)

    # -- Show overlay --------------------------------------------------------
    def _show_overlay(self, text):
        if self.overlay is None:
            self.overlay = OverlayWindow(self.engine_key)
        else:
            self.overlay.set_engine(self.engine_key)
        self.overlay.set_text(text, self.region)

    # -- Help card -----------------------------------------------------------
    def _help_text(self):
        return (
            "<b style='color:#9d8fff;'>3 steps to get started:</b><br>"
            "&nbsp;&nbsp;<b style='color:#7c6af7;'>1)</b> Pick an engine (Google works without an API key), set source/target languages.<br>"
            "&nbsp;&nbsp;<b style='color:#7c6af7;'>2)</b> Use <b>\U0001f4d0 Pick Region</b> to drag a box around the subtitle/dialog area. "
            "Don't make it too tight - leave ~10px of padding.<br>"
            "&nbsp;&nbsp;<b style='color:#7c6af7;'>3)</b> Click <b>✨ Find Mode</b> to auto-detect the best OCR mode, then <b>▶ START</b>.<br><br>"
            "<b style='color:#9d8fff;'>Tips:</b><br>"
            "&nbsp;&nbsp;•  Enable <b>Fast subtitle</b> for games like RDR2/SM2 (0.4s interval, aggressive change detection).<br>"
            "&nbsp;&nbsp;•  Try the <b>Stroke</b> or <b>Equalize</b> mode for bright/complex backgrounds.<br>"
            "&nbsp;&nbsp;•  <b>Glossary</b> (Settings): protects proper names - <code>Dutch=Dutch</code>, <code>Arthur=Arthur</code>.<br>"
            "&nbsp;&nbsp;•  <b>Global shortcuts</b> (Settings): Ctrl+Alt+R/T/G work while the game is fullscreen.<br>"
            "&nbsp;&nbsp;•  <b>Auto-pause</b>: scanning stops automatically when you Alt-Tab away and resumes when you return.<br>"
            "&nbsp;&nbsp;•  With minimize-to-tray, the X button hides the app instead of closing it."
        )

    def _toggle_help(self):
        if self.help_card.isVisible():
            self.help_card.hide()
            self.help_toggle.setText("\U0001f4a1  Quick start (show)")
        else:
            self.help_card.show()
            self.help_toggle.setText("\U0001f4a1  Quick start (hide)")

    # -- Automatic mode detection --------------------------------------------
    def _auto_detect_mode(self):
        if not self.region:
            QMessageBox.warning(self, "Warning", "Pick a region first!")
            return
        self.bridge.status.emit("● Trying modes...", WARNING)
        threading.Thread(target=self._auto_detect_worker, daemon=True).start()

    def _auto_detect_worker(self):
        try:
            raw = GRABBER.grab(self.region)
        except Exception as e:
            self.bridge.status.emit(f"● Capture error: {e}", ERROR)
            return

        lang = OCR_LANG_MAP.get(self.src_combo.currentText(), "eng")
        psm_val = self.ocr_psm.split(" ")[0]
        config = (f"--oem 3 --psm {psm_val} -c preserve_interword_spaces=1 "
                  f"-c tessedit_char_blacklist=©®™€¥§¶•")

        best = None  # (score, mode, sample_text)
        for mode_key, mode_label in OCR_MODES:
            try:
                proc = preprocess(raw, self.ocr_scale, mode_key)
                data = pytesseract.image_to_data(
                    proc, lang=lang, config=config,
                    output_type=pytesseract.Output.DICT)
            except Exception as e:
                self.bridge.log.emit(f"[{mode_label}] error: {e}", "warn")
                continue

            score, word_count, sample = 0.0, 0, []
            for i, w in enumerate(data.get("text", [])):
                w = (w or "").strip()
                if not w or is_noise_word(w):
                    continue
                try:
                    conf = int(float(data["conf"][i]))
                except Exception:
                    conf = -1
                if conf < 50:
                    continue
                score += conf
                word_count += 1
                if len(sample) < 6:
                    sample.append(w)
            # Too few words -> probably noise
            if word_count < 2:
                continue
            self.bridge.log.emit(
                f"[{mode_label}] {word_count} words · score {int(score)} · "
                f"{' '.join(sample)[:50]}", "dim")
            if best is None or score > best[0]:
                best = (score, mode_key, mode_label)

        if best is None:
            self.bridge.status.emit("● No text found in any mode", ERROR)
            return

        self.ocr_mode = best[1]
        self.bridge.status.emit(f"● Best mode: {best[2]} (score {int(best[0])})", SUCCESS)
        self.bridge.log.emit(f"OCR mode -> {best[2]}", "ok")
        self._save_config()

    # -- System tray ---------------------------------------------------------
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(make_tray_icon(False), self)
        self._tray.setToolTip("SubLens")

        menu = QMenu()
        a_show = QAction("Show / Hide", self)
        a_show.triggered.connect(self._toggle_window_visible)
        a_scan = QAction("Start / Stop (scanning)", self)
        a_scan.triggered.connect(self._toggle_scan)
        a_hide_ov = QAction("Hide overlay", self)
        a_hide_ov.triggered.connect(self._hide_overlay)
        a_quit = QAction("Quit", self)
        a_quit.triggered.connect(self._real_quit)

        menu.addAction(a_show)
        menu.addAction(a_scan)
        menu.addAction(a_hide_ov)
        menu.addSeparator()
        menu.addAction(a_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._toggle_window_visible()

    def _toggle_window_visible(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()
            self.raise_()

    def _real_quit(self):
        self._force_quit = True
        self.close()

    # -- Global hotkeys ------------------------------------------------------
    def _register_global_hotkeys(self):
        if not HAS_KEYBOARD:
            self._append_log(
                "Global shortcuts need 'keyboard'  ·  pip install keyboard", "warn")
            return
        self._unregister_global_hotkeys()
        try:
            # F2/F3/F4 + Ctrl+Alt alternatives (fallback when games steal the keys)
            self._registered_hotkeys = [
                keyboard.add_hotkey("f2", lambda: self.bridge.trigger_pick.emit()),
                keyboard.add_hotkey("f3", lambda: self.bridge.trigger_once.emit()),
                keyboard.add_hotkey("f4", lambda: self.bridge.trigger_toggle.emit()),
                keyboard.add_hotkey("ctrl+alt+r", lambda: self.bridge.trigger_pick.emit()),
                keyboard.add_hotkey("ctrl+alt+t", lambda: self.bridge.trigger_once.emit()),
                keyboard.add_hotkey("ctrl+alt+g", lambda: self.bridge.trigger_toggle.emit()),
                keyboard.add_hotkey("ctrl+alt+h", lambda: self.bridge.trigger_hide_overlay.emit()),
            ]
            self._append_log(
                "Global shortcuts: F2/F3/F4  +  Ctrl+Alt+R/T/G/H  (work while the game is fullscreen)",
                "ok")
        except Exception as e:
            self._append_log(f"Failed to register global shortcuts: {e}", "err")

    def _unregister_global_hotkeys(self):
        if not HAS_KEYBOARD:
            return
        for h in self._registered_hotkeys:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._registered_hotkeys = []

    # -- Auto-pause ----------------------------------------------------------
    def _check_auto_pause(self):
        if not (self.running and self.auto_pause_on and HAS_WIN32):
            return
        hwnd, pid, _title = get_foreground_info()
        if not hwnd:
            return
        # If our own process is focused, don't accept it as target but also
        # don't pause (the user may be looking at Settings)
        if pid == self._self_pid:
            return
        # No target yet -> set the first external window we see
        if self._target_hwnd == 0:
            self._target_hwnd = hwnd
            self._append_log(
                f"Auto-pause target acquired: {_title[:40] or '(untitled)'}", "dim")
            if self._paused:
                self._paused = False
            return
        # Is the target window in the foreground?
        if hwnd == self._target_hwnd:
            if self._paused:
                self._paused = False
                self._append_log("Auto-pause: resumed", "ok")
        else:
            if not self._paused:
                self._paused = True
                self._append_log(f"Auto-pause: paused ({_title[:30]})", "warn")

    # -- Test engine ---------------------------------------------------------
    def _test_engine(self, key):
        eng = self.ENGINES[key]
        self.bridge.status.emit(f"● Testing {eng.name}...", WARNING)

        def _run():
            try:
                if key == "lmstudio":
                    eng.url = self.lm_url
                    eng.model = self.lm_model
                    models = eng.test()
                    self.bridge.models.emit(models)
                    msg = f"Connected  ·  {len(models)} models"
                elif key == "deepl":
                    eng.api_key = self.deepl_key
                    msg = eng.test()
                else:
                    msg = eng.test()
                self.bridge.status.emit(f"● {msg}", SUCCESS)
                self.bridge.log.emit(f"[{eng.name}] {msg}", "ok")
            except Exception as e:
                self.bridge.status.emit(f"● Error: {e}", ERROR)
                self.bridge.log.emit(f"[{eng.name}] Error: {e}", "err")

        threading.Thread(target=_run, daemon=True).start()

    # -- Settings window -----------------------------------------------------
    def _open_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.resize(520, 720)
        dlg.setStyleSheet(self.styleSheet())

        scroll = QScrollArea(dlg); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        content = QWidget(); scroll.setWidget(content)
        v = QVBoxLayout(content); v.setContentsMargins(20, 18, 20, 12); v.setSpacing(8)

        def section(title):
            row = QHBoxLayout()
            l = QLabel(title); l.setStyleSheet(f"color: {TEXT_DIM}; font: bold 9pt 'Consolas'; letter-spacing: 1px;")
            row.addWidget(l)
            sep = QFrame(); sep.setStyleSheet(f"background: {BORDER}; max-height: 1px;")
            sep.setMinimumHeight(1)
            row.addWidget(sep, 1)
            wr = QWidget(); wr.setLayout(row)
            v.addSpacing(6)
            v.addWidget(wr)

        # LM Studio
        section("LM STUDIO  (local AI)")
        url_row = QHBoxLayout()
        url_row.addWidget(self._dim("URL:"))
        url_edit = QLineEdit(self.lm_url); url_edit.setMinimumWidth(220)
        url_row.addWidget(url_edit, 1)
        url_test = QPushButton("Connect")
        url_test.setStyleSheet(f"background: {ENGINE_ACCENT['lmstudio']}; color: {BG_DARK};")
        url_row.addWidget(url_test)
        v.addLayout(url_row)

        model_row = QHBoxLayout()
        model_row.addWidget(self._dim("Model:"))
        self.lm_combo = QComboBox(); self.lm_combo.setEditable(True)
        self.lm_combo.addItem(self.lm_model)
        self.lm_combo.setCurrentText(self.lm_model)
        model_row.addWidget(self.lm_combo, 1)
        v.addLayout(model_row)

        # DeepL
        section("DEEPL FREE  (500k characters/month)")
        deepl_row = QHBoxLayout()
        deepl_row.addWidget(self._dim("API Key:"))
        key_edit = QLineEdit(self.deepl_key); key_edit.setEchoMode(QLineEdit.Password)
        deepl_row.addWidget(key_edit, 1)
        deepl_test = QPushButton("Test")
        deepl_test.setStyleSheet(f"background: {ENGINE_ACCENT['deepl']}; color: {BG_DARK};")
        deepl_row.addWidget(deepl_test)
        v.addLayout(deepl_row)
        v.addWidget(self._dim("deepl.com -> API Free plan -> free signup is enough"))

        # Google
        section("GOOGLE TRANSLATE")
        google_row = QHBoxLayout()
        gtest = QPushButton("Test")
        gtest.setStyleSheet(f"background: {ENGINE_ACCENT['google']}; color: {BG_DARK};")
        google_row.addWidget(gtest)
        google_row.addWidget(self._dim("  Unofficial endpoint, may be blocked at times"))
        google_row.addStretch(1)
        v.addLayout(google_row)

        # Context
        section("GAME CONTEXT  (optional)")
        v.addWidget(self._dim("E.g.: 'Wild West, 1899, cowboy dialogue'"))
        ctx_edit = QLineEdit(self.ctx)
        v.addWidget(ctx_edit)

        # OCR
        section("OCR")
        # scale
        scale_row = QHBoxLayout()
        scale_row.addWidget(self._dim("Upscale:"))
        scale_grp = QButtonGroup(dlg)
        for val in (2, 3, 4):
            rb = QRadioButton(f"{val}x")
            if val == self.ocr_scale:
                rb.setChecked(True)
            scale_grp.addButton(rb, val)
            scale_row.addWidget(rb)
        scale_row.addStretch(1)
        v.addLayout(scale_row)

        # mode
        mode_row = QGridLayout()
        mode_row.addWidget(self._dim("Text:"), 0, 0)
        mode_grp = QButtonGroup(dlg)
        for idx, (val, lbl) in enumerate(OCR_MODES):
            rb = QRadioButton(lbl)
            if val == self.ocr_mode:
                rb.setChecked(True)
            rb.setProperty("mode", val)
            mode_grp.addButton(rb, idx)
            r, c = divmod(idx, 2)
            mode_row.addWidget(rb, r, 1 + c)
        v.addLayout(mode_row)

        # PSM
        psm_row = QHBoxLayout()
        psm_row.addWidget(self._dim("PSM:"))
        psm_combo = QComboBox(); psm_combo.addItems(PSM_OPTIONS)
        psm_combo.setCurrentText(self.ocr_psm)
        psm_row.addWidget(psm_combo, 1)
        v.addLayout(psm_row)

        # -- Glossary (term protection) --
        section("GLOSSARY  (proper-name / term protection)")
        v.addWidget(self._dim(
            "One rule per line:  source=target   (write only 'source' to skip translation)\n"
            "E.g.:  Dutch=Dutch     Arthur=Arthur     Saint Denis=Saint Denis     # comment"))
        glossary_edit = QPlainTextEdit(self.glossary_text)
        glossary_edit.setPlaceholderText(
            "Arthur=Arthur\nDutch=Dutch\nVan der Linde=Van der Linde\n# RDR2 example\n")
        glossary_edit.setMinimumHeight(120)
        glossary_edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {BG_CARD}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; padding: 8px; "
            f"font-family: 'Consolas'; font-size: 10pt; }}")
        v.addWidget(glossary_edit)

        # -- Runtime preferences --
        section("RUNTIME")
        gh_cb = QCheckBox(
            "Global shortcuts (Ctrl+Alt+R / T / G / H) - work while the game is fullscreen")
        gh_cb.setChecked(self.global_hotkeys_on)
        if not HAS_KEYBOARD:
            gh_cb.setEnabled(False)
            gh_cb.setText(gh_cb.text() + "  [keyboard not installed]")
        v.addWidget(gh_cb)

        ap_cb = QCheckBox(
            "Auto-pause - pause scanning when the game window loses focus")
        ap_cb.setChecked(self.auto_pause_on)
        if not HAS_WIN32:
            ap_cb.setEnabled(False)
            ap_cb.setText(ap_cb.text() + "  [pywin32 not installed]")
        v.addWidget(ap_cb)

        tr_cb = QCheckBox("Minimize to tray on close (use the tray menu to actually quit)")
        tr_cb.setChecked(self.minimize_to_tray)
        v.addWidget(tr_cb)

        v.addStretch(1)

        # Bottom button bar
        outer = QVBoxLayout(dlg); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll, 1)
        sep = QFrame(); sep.setStyleSheet(f"background: {BORDER}; max-height: 1px;")
        outer.addWidget(sep)
        btn_row = QHBoxLayout(); btn_row.setContentsMargins(20, 10, 20, 12)
        btn_row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(f"background: {BG_CARD}; color: {TEXT_PRIMARY};")
        cancel.clicked.connect(dlg.reject)
        save = QPushButton("✓  Save")
        save.setStyleSheet(f"background: {SUCCESS}; color: {BG_DARK};")
        btn_row.addWidget(cancel); btn_row.addWidget(save)
        outer.addLayout(btn_row)

        # Bindings
        url_test.clicked.connect(lambda: (
            setattr(self, "lm_url", url_edit.text().strip()),
            setattr(self, "lm_model", self.lm_combo.currentText().strip()),
            self._test_engine("lmstudio")))
        deepl_test.clicked.connect(lambda: (
            setattr(self, "deepl_key", key_edit.text().strip()),
            self._test_engine("deepl")))
        gtest.clicked.connect(lambda: self._test_engine("google"))

        def _save_and_close():
            self.lm_url = url_edit.text().strip()
            self.lm_model = self.lm_combo.currentText().strip()
            self.deepl_key = key_edit.text().strip()
            self.ctx = ctx_edit.text().strip()
            self.ocr_scale = scale_grp.checkedId() if scale_grp.checkedId() != -1 else self.ocr_scale
            mode_id = mode_grp.checkedId()
            if mode_id != -1:
                self.ocr_mode = OCR_MODES[mode_id][0]
            self.ocr_psm = psm_combo.currentText()

            # Glossary
            self.glossary_text = glossary_edit.toPlainText()
            self.glossary = parse_glossary(self.glossary_text)
            self._cache = LRUCache(200)  # clear cache (glossary may have changed)

            # Runtime preferences
            prev_gh = self.global_hotkeys_on
            prev_ap = self.auto_pause_on
            self.global_hotkeys_on = gh_cb.isChecked()
            self.auto_pause_on = ap_cb.isChecked()
            self.minimize_to_tray = tr_cb.isChecked()

            if self.global_hotkeys_on and not prev_gh:
                self._register_global_hotkeys()
            elif prev_gh and not self.global_hotkeys_on:
                self._unregister_global_hotkeys()
                self._append_log("Global shortcuts disabled", "dim")

            if self.auto_pause_on and not prev_ap:
                self._pause_timer.start()
                self._append_log("Auto-pause enabled", "ok")
            elif prev_ap and not self.auto_pause_on:
                self._pause_timer.stop()
                self._paused = False
                self._target_hwnd = 0

            self._save_config()
            self.bridge.status.emit("● Settings saved", SUCCESS)
            dlg.accept()
            self._refresh_preview()

        save.clicked.connect(_save_and_close)

        def _cleanup():
            self.lm_combo = None
        dlg.finished.connect(lambda _: _cleanup())

        dlg.exec()

    # -- Info window ---------------------------------------------------------
    def _open_info(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Info  ·  SubLens")
        dlg.resize(720, 640)
        dlg.setStyleSheet(self.styleSheet())

        v = QVBoxLayout(dlg); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        hdr = QLabel("ⓘ  USER GUIDE")
        hdr.setStyleSheet(f"color: {ACCENT}; font: bold 14pt 'Segoe UI'; padding: 14px 20px;")
        v.addWidget(hdr)
        bar = QFrame(); bar.setStyleSheet(f"background: {ACCENT}; max-height: 2px;")
        v.addWidget(bar)

        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setStyleSheet(
            f"QTextBrowser {{ background: {BG_CARD}; color: {TEXT_PRIMARY}; "
            f"border: none; padding: 16px 20px; font-family: 'Segoe UI'; font-size: 10pt; }}")
        readme = Path(__file__).with_name("READMEapp.md")
        try:
            md = readme.read_text(encoding="utf-8") + "\n\n---\n\n"
        except Exception:
            md = ""
        md += self._builtin_guide()
        tb.setMarkdown(md)
        v.addWidget(tb, 1)

        dlg.exec()

    def _builtin_guide(self) -> str:
        return """# SubLens - User guide

## Quick start (3 steps)

1. **Pick an engine.** Google works without an API key and is quick to set up. DeepL is higher quality but needs an API key. LM Studio runs locally (offline).
2. **Pick Region (F2)** to drag a rectangle around the subtitle/dialog box. Leave **~10 px of padding** around the text (Tesseract struggles right at the edges).
3. **Find Mode** to auto-detect the best OCR mode, then **START (F4)**.

## What does each mode do?

| Mode | When to use |
|---|---|
| **Automatic** | Clear subtitles, uniform background |
| **Light text / dark background** | Classic black background + white text |
| **Dark text / light background** | Menus, white backgrounds |
| **Subtitle (top-hat)** | Semi-transparent subtitle box over a varying background |
| **Outlined (Stroke)** | RDR2, Spider-Man 2 - text with a black outline |
| **Complex background (Equalize)** | Bright, busy backgrounds; sky, fire, etc. |

If you're not sure, click **Find Mode**; it tries 6 modes and picks the one with the highest OCR confidence.

## Shortcuts

**When the window is focused (always works):**
- `F2` Pick region · `F3` Translate once · `F4` Start/Stop · `ESC` Hide overlay

**Global (while the game is fullscreen - must be enabled in Settings):**
- `Ctrl+Alt+R` Region · `Ctrl+Alt+T` Once · `Ctrl+Alt+G` Start/Stop · `Ctrl+Alt+H` Hide overlay

## Glossary (term protection)

Settings -> GLOSSARY. One rule per line:
```
Arthur=Arthur
Dutch=Dutch
Saint Denis=Saint Denis
Van der Linde=Van der Linde
# comment line
```
A rule **hides the term** in the source text before translation and writes it back afterwards. This avoids mistakes like "Dutch" -> "Hollander". If you write only `source`, that term won't be translated at all.

## Auto-pause

When enabled: as scanning starts, the **first external window** (the game) is taken as the target. OCR/API calls pause when you Alt-Tab to another app, and resume when you return.
- To change the target: stop scanning -> focus the game -> start again.

## Tray (system tray)

- The X button hides the app to the tray instead of closing it (can be turned off in settings).
- Tray icon **green** = scanning, **purple** = idle.
- Tray menu: Show/Hide · Start/Stop · Hide overlay · **Quit**.

## Fast subtitle mode

Checkbox on the main screen. Drops the interval to 0.4 s and loosens the change-detection threshold. Useful for fast-dialog games like RDR2, Spider-Man 2, GTA. Increases CPU and API usage.

## Troubleshooting

- **OCR empty** -> Enlarge the region a bit, try **Find Mode**, set OCR upscale to 4x.
- **Emoji/icons leaking in** -> They're filtered automatically; if the problem persists, narrow the region to just the text line.
- **Global hotkey not working** -> `pip install keyboard`. On Windows, some games are admin-protected; run the app as administrator.
- **Auto-pause targets the wrong window** -> Stop scanning, Alt-Tab to the game window, then start again.
- **DeepL 429** -> You've hit the free monthly quota; wait for next month or switch engine.
"""


# -----------------------------------------------------------------------------

def warn_tesseract_missing():
    """Warn the user when Tesseract is missing and provide a download link."""
    box = QMessageBox()
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle("Tesseract OCR not found  ·  SubLens")
    box.setTextFormat(Qt.RichText)
    box.setText(
        "<b>SubLens requires Tesseract OCR to read text.</b><br><br>"
        "It was not found on the system. Without OCR, on-screen text "
        "cannot be read and translation will not work.")
    box.setInformativeText(
        f"Installation page:<br><a href='{TESSERACT_URL}'>{TESSERACT_URL}</a><br><br>"
        "During installation, check <b>Turkish (tur)</b> and the other "
        "languages you'll use under <b>Additional language data</b>.<br><br>"
        "Install to the default location (C:\\Program Files\\Tesseract-OCR), "
        "restart SubLens - it will be detected automatically.")
    dl_btn = box.addButton("Open download page", QMessageBox.AcceptRole)
    box.addButton("Continue anyway", QMessageBox.RejectRole)
    box.setDefaultButton(dl_btn)
    box.exec()
    if box.clickedButton() is dl_btn:
        QDesktopServices.openUrl(QUrl(TESSERACT_URL))


def main():
    # On Qt6, High-DPI scaling is default; no need to enable it explicitly.
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Don't quit the app when the window is hidden to the tray
    app.setQuitOnLastWindowClosed(False)

    # App icon (use the runtime tray icon if no embedded .ico is available)
    ico_path = Path(__file__).with_name("SubLens.ico")
    if getattr(sys, "frozen", False):
        ico_path = Path(sys._MEIPASS) / "SubLens.ico"
    if ico_path.exists():
        app.setWindowIcon(QIcon(str(ico_path)))
    else:
        app.setWindowIcon(make_tray_icon(False))

    # Tesseract check
    if not _tess_path:
        warn_tesseract_missing()
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(BG_DARK))
    pal.setColor(QPalette.Base, QColor(BG_CARD))
    pal.setColor(QPalette.Text, QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(BG_DARK))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
