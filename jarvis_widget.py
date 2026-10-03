"""
jarvis_widget.py — J.A.R.V.I.S Avengers-Style Desktop Companion Reactor
========================================================================
Standalone always-on-top transparent PyQt5 widget.

Architecture:
  - Separate process from companion.py (avoids PyQt5 vs pywebview event loop conflict)
  - Communicates with JARVIS backend at http://127.0.0.1:8000 via HTTP polling
  - Reads state from /status endpoint
  - Opens companion.py (main JARVIS window) on click
  - Single-instance protected via Windows mutex
  - System tray accessible
  - Global hotkey: Ctrl+Shift+J to toggle companion visibility

Visual Layers:
  1. Energy nucleus         -- faceted hexagonal crystalline core
  2. Arc containment rings  -- nested transparent rings different radii/speeds
  3. Orbital mechanics      -- elliptical orbiting energy particles with trails
  4. Mechanical segments    -- broken-ring tech segments that rotate and lock
  5. Plasma particles       -- controlled particle field around core
  6. Holographic scan arcs  -- thin slow-moving scan sweep
  7. Radial tick glyphs     -- Stark-inspired radial marks

State mapping:
  IDLE      -> slow rotation, breathing nucleus, faint pulse
  LISTENING -> outer rings expand, red accent waveform ring
  THINKING  -> faster orbitals, amber/cyan intelligence sweep
  EXECUTING -> targeting brackets, ring lock, directional amber pulse
  SPEAKING  -> radial oscillation, cyan pulse modulation
  ERROR     -> red/amber warning + contraction -> auto-return to idle after 3s
"""

import sys
import os
import math
import time
import json
import ctypes
import threading
import subprocess
import random
import logging
from pathlib import Path

try:
    from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QThread, pyqtSignal
    from PyQt5.QtGui import (
        QPainter, QColor, QPen, QBrush, QRadialGradient, QPolygonF,
        QPainterPath, QPixmap, QIcon, QFont
    )
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QSystemTrayIcon, QMenu, QAction, QDesktopWidget
    )
except ImportError as e:
    print(f"PyQt5 not found: {e}. Install with: pip install PyQt5")
    sys.exit(1)

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import keyboard as _kb
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("JarvisWidget")

# ---- Single-Instance Mutex ---------------------------------------------------
WIDGET_MUTEX_NAME = "JarvisP1_Widget_Mutex_v2"
_mutex_handle = None

def _acquire_mutex():
    global _mutex_handle
    h = ctypes.windll.kernel32.CreateMutexW(None, False, WIDGET_MUTEX_NAME)
    if not h:
        return False
    res = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
    if res == 0x102:  # WAIT_TIMEOUT
        ctypes.windll.kernel32.CloseHandle(h)
        log.error("JARVIS widget already running.")
        return False
    _mutex_handle = h
    return True

def _release_mutex():
    global _mutex_handle
    if _mutex_handle:
        try:
            ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        except Exception:
            pass
        _mutex_handle = None

# ---- Constants --------------------------------------------------------------
BACKEND_URL    = "http://127.0.0.1:8000"
COMPANION_SCRIPT = str(Path(__file__).parent / "companion.py")
WIDGET_SIZE    = 200
HALF           = WIDGET_SIZE / 2.0

class ReactorState:
    IDLE      = "idle"
    LISTENING = "listening"
    THINKING  = "thinking"
    EXECUTING = "executing"
    SPEAKING  = "speaking"
    ERROR     = "error"

# ---- Particle ---------------------------------------------------------------
class Particle:
    def __init__(self, orbit_r, speed, phase, tilt=0.0, size=2.0):
        self.orbit_r = orbit_r
        self.speed   = speed
        self.angle   = phase
        self.tilt    = tilt
        self.size    = size
        self.alpha   = random.randint(140, 220)
        self.flicker = random.uniform(0.9, 1.1)

    def update(self, dt, speed_mul):
        self.angle += self.speed * dt * speed_mul

    def pos(self):
        x = self.orbit_r * math.cos(self.angle)
        y = self.orbit_r * math.sin(self.angle) * (1.0 - self.tilt * 0.55)
        return QPointF(x, y)

# ---- Backend Polling Thread -------------------------------------------------
class BackendPoller(QThread):
    state_changed  = pyqtSignal(str)
    backend_online = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._running  = True
        self._last_ok  = None

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            ok = False
            state = ReactorState.IDLE
            if HAS_REQUESTS:
                try:
                    r = _req.get(f"{BACKEND_URL}/status", timeout=0.8)
                    if r.status_code == 200:
                        data = r.json()
                        state = data.get("state", ReactorState.IDLE)
                        ok = True
                except Exception:
                    pass
            if ok != self._last_ok:
                self._last_ok = ok
                self.backend_online.emit(ok)
            self.state_changed.emit(state)
            time.sleep(0.5)

# ---- Helper color blend -----------------------------------------------------
def blend(a, b, t):
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red()   * (1-t) + b.red()   * t),
        int(a.green() * (1-t) + b.green() * t),
        int(a.blue()  * (1-t) + b.blue()  * t),
        int(a.alpha() * (1-t) + b.alpha() * t),
    )

# ---- The Widget -------------------------------------------------------------
class JarvisReactorWidget(QWidget):

    def __init__(self):
        super().__init__()
        self._state       = ReactorState.IDLE
        self._state_t     = 0.0
        self._error_ttl   = 0.0
        self._t           = 0.0
        self._dt          = 1.0/60.0

        # Lerped visual parameters
        self._speed_mul   = 1.0
        self._brightness  = 1.0
        self._outer_scale = 1.0
        self._accent_aa   = 0.0   # amber accent 0..1
        self._error_aa    = 0.0   # error red 0..1

        # Nucleus breathing
        self._breath      = 0.0
        self._nuc_r       = 14.0

        # Scan arc
        self._scan_ang    = 0.0
        self._scan_alpha  = 0.0

        # Tick lights (32 radial marks, occasionally illuminated)
        self._tick_ang    = [i * (math.pi*2/32) for i in range(32)]
        self._tick_lit    = [False]*32

        self._drag_pos    = None
        self._backend_ok  = False

        # Rings: (radius, thickness, angular_speed, gap_count, base_alpha, direction)
        self._rings = [
            (26,  1.2,  0.30,  0, 90,  1),
            (36,  0.7,  0.50,  0, 70, -1),
            (46,  1.4, -0.35, 14, 60,  1),
            (57,  0.6,  0.55,  0, 50, -1),
            (67,  1.0,  0.20, 20, 40,  1),
            (78,  0.5, -0.28,  0, 28, -1),
            (88,  1.1,  0.14,  0, 18,  1),
        ]
        self._ring_a = [random.uniform(0, math.pi*2) for _ in self._rings]

        # Orbital particles (radius, speed, start_phase, tilt, size)
        self._orbitals = [
            Particle(38, 1.10, 0.0,          0.20, 2.5),
            Particle(38, 1.10, math.pi,       0.20, 2.5),
            Particle(52, 0.70, 1.0,           0.40, 2.0),
            Particle(52, 0.70, 4.2,           0.40, 2.0),
            Particle(62, 0.50, 2.5,           0.60, 1.8),
            Particle(72, 0.35, 0.8,           0.35, 1.5),
            Particle(72, 0.35, math.pi+0.8,   0.35, 1.5),
        ]

        # Plasma particle field
        self._plasma = []
        for _ in range(28):
            r  = random.uniform(28, 80)
            sp = random.uniform(0.3, 1.4) * random.choice([-1,1])
            ph = random.uniform(0, math.pi*2)
            ti = random.uniform(0, 0.7)
            sz = random.uniform(1.0, 2.8)
            self._plasma.append(Particle(r, sp, ph, ti, sz))

        self._setup_window()
        self._setup_tray()
        self._setup_timer()
        self._setup_hotkey()
        self._setup_poller()

        # Scan trigger
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._trigger_scan)
        self._scan_timer.start(4000 + random.randint(0, 3000))

        # Tick light pulse
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._pulse_tick)
        self._tick_timer.start(300)

    # ---- Window setup -------------------------------------------------------
    def _setup_window(self):
        self.setFixedSize(WIDGET_SIZE, WIDGET_SIZE)
        # Qt.Tool    → no taskbar button
        # WindowStaysOnBottomHint → stays behind normal windows (desktop-pet behavior)
        # WindowDoesNotAcceptFocus → companion never steals focus
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnBottomHint |
            Qt.WindowDoesNotAcceptFocus |
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("J.A.R.V.I.S")

        # Load saved position or default to bottom-right corner
        self._load_position()

    # ---- Position persistence -----------------------------------------------
    _CONFIG_FILE = os.path.join(os.path.dirname(__file__), "companion_config.json")

    def _load_position(self):
        try:
            if os.path.exists(self._CONFIG_FILE):
                with open(self._CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                pos = cfg.get("ReactorWidget")
                if pos and "x" in pos and "y" in pos:
                    self.move(pos["x"], pos["y"])
                    return
        except Exception:
            pass
        # Default: bottom-right corner of primary screen
        desk = QDesktopWidget().availableGeometry()
        self.move(desk.right() - WIDGET_SIZE - 40, desk.bottom() - WIDGET_SIZE - 60)

    def _save_position(self):
        try:
            cfg = {}
            if os.path.exists(self._CONFIG_FILE):
                with open(self._CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
            cfg["ReactorWidget"] = {"x": self.x(), "y": self.y()}
            with open(self._CONFIG_FILE, "w") as f:
                json.dump(cfg, f)
        except Exception:
            pass

    # ---- Tray ---------------------------------------------------------------
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("System tray not available.")
            return

        # Try loading the actual icon first, fall back to drawn icon
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "jarvis_icon.ico")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
        else:
            pm = QPixmap(64, 64)
            pm.fill(QColor(0, 0, 0, 0))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            cx = cy = 32
            g = QRadialGradient(cx, cy, 28)
            g.setColorAt(0, QColor(0, 212, 255, 255))
            g.setColorAt(0.5, QColor(0, 100, 170, 200))
            g.setColorAt(1, QColor(0, 30, 60, 0))
            p.setBrush(QBrush(g)); p.setPen(Qt.NoPen)
            p.drawEllipse(cx-26, cy-26, 52, 52)
            p.setPen(QPen(QColor(0, 200, 240, 180), 2)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(cx-30, cy-30, 60, 60)
            p.end()
            icon = QIcon(pm)

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("J.A.R.V.I.S")

        MENU_CSS = """
            QMenu { background:#0a1520; border:1px solid #006688; color:#a0d8f0;
                    font-family:'Segoe UI'; font-size:10px; padding:4px; border-radius:4px; }
            QMenu::item { padding:5px 18px; border-radius:2px; }
            QMenu::item:selected { background:#004455; color:#00d4ff; }
            QMenu::separator { height:1px; background:#003344; margin:3px 4px; }
        """
        menu = QMenu(); menu.setStyleSheet(MENU_CSS)
        acts = [
            ("Open J.A.R.V.I.S",      self._open_main_jarvis),
            ("---", None),
            ("Show Companion",         self._show_companion),
            ("Hide Companion",         self.hide),
            ("---", None),
            ("Voice",                  self._toggle_voice),
            ("Settings",               self._open_settings),
            ("---", None),
            ("Restart Companion",      self._restart_companion),
            ("Exit J.A.R.V.I.S",      self._quit),
        ]
        for label, cb in acts:
            if label == "---":
                menu.addSeparator()
            else:
                a = QAction(label, self)
                a.triggered.connect(cb)
                menu.addAction(a)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._open_main_jarvis()

    # ---- Timer --------------------------------------------------------------
    def _setup_timer(self):
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._tick)
        self._render_timer.start(16)

    # ---- Hotkey -------------------------------------------------------------
    def _setup_hotkey(self):
        if not HAS_KEYBOARD:
            return
        try:
            _kb.add_hotkey("ctrl+shift+j", lambda: QTimer.singleShot(0, self._toggle_vis))
            log.info("Widget hotkey registered: Ctrl+Shift+J")
        except Exception as e:
            log.warning(f"Hotkey registration failed: {e}")

    def _toggle_vis(self):
        if self.isVisible(): self.hide()
        else: self.show(); self.raise_()

    # ---- Backend poller -----------------------------------------------------
    def _setup_poller(self):
        self._poller = BackendPoller()
        self._poller.state_changed.connect(self._on_state)
        self._poller.backend_online.connect(self._on_online)
        self._poller.start()

    def _on_state(self, s):  self.set_state(s)
    def _on_online(self, ok): self._backend_ok = ok

    # ---- State --------------------------------------------------------------
    def set_state(self, state):
        if state == self._state:
            return
        self._state   = state
        self._state_t = 0.0
        if state == ReactorState.ERROR:
            self._error_ttl = 3.0

    # ---- Animation tick -----------------------------------------------------
    def _tick(self):
        self._t      += self._dt
        self._state_t += self._dt

        if self._state == ReactorState.ERROR:
            self._error_ttl -= self._dt
            if self._error_ttl <= 0:
                self.set_state(ReactorState.IDLE)

        # Target params per state
        s = self._state
        if   s == ReactorState.IDLE:      tm,tb,to,ta,te = 1.0, 1.0, 1.0, 0.0, 0.0
        elif s == ReactorState.LISTENING: tm,tb,to,ta,te = 1.6, 1.3, 1.15,0.0, 0.0
        elif s == ReactorState.THINKING:  tm,tb,to,ta,te = 2.2, 1.2, 1.0, 0.7, 0.0
        elif s == ReactorState.EXECUTING: tm,tb,to,ta,te = 2.8, 1.4, 1.1, 0.9, 0.0
        elif s == ReactorState.SPEAKING:  tm,tb,to,ta,te = 1.5, 1.25,1.05,0.3, 0.0
        elif s == ReactorState.ERROR:     tm,tb,to,ta,te = 3.0, 0.7, 0.9, 0.0, 1.0
        else:                             tm,tb,to,ta,te = 1.0, 1.0, 1.0, 0.0, 0.0

        lr = 0.04
        self._speed_mul   = self._lerp(self._speed_mul,   tm, lr)
        self._brightness  = self._lerp(self._brightness,  tb, lr)
        self._outer_scale = self._lerp(self._outer_scale, to, lr)
        self._accent_aa   = self._lerp(self._accent_aa,   ta, lr)
        self._error_aa    = self._lerp(self._error_aa,    te, lr)

        # Nucleus breathing
        self._breath += self._dt * 1.2
        self._nuc_r   = 14.0 + math.sin(self._breath) * 2.5 * self._brightness

        # Ring rotation
        for i, (r, t, sp, g, a, d) in enumerate(self._rings):
            self._ring_a[i] += sp * self._dt * self._speed_mul * d

        # Particles
        for p in self._plasma + self._orbitals:
            p.update(self._dt, self._speed_mul)

        # Scan
        if self._scan_alpha > 0:
            self._scan_ang   += self._dt * 0.8 * self._speed_mul
            self._scan_alpha  = self._lerp(self._scan_alpha, 0.0, 0.02)
            if self._scan_alpha < 0.005:
                self._scan_alpha = 0.0

        self.update()

    @staticmethod
    def _lerp(a, b, t):
        return a + (b - a) * t

    def _trigger_scan(self):
        self._scan_alpha = 0.90
        self._scan_ang   = random.uniform(0, math.pi*2)
        self._scan_timer.setInterval(3000 + random.randint(0, 4000))

    def _pulse_tick(self):
        idx = random.randint(0, 31)
        self._tick_lit[idx] = True
        for i in range(32):
            if i != idx and random.random() < 0.3:
                self._tick_lit[i] = False

    # ---- Paint event --------------------------------------------------------
    def paintEvent(self, event):
        p  = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # Temporary background fill to debug visibility
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

        cx = cy = HALF
        t  = self._t
        sp = self._speed_mul
        br = self._brightness
        ea = self._error_aa
        aa = self._accent_aa

        # ---- Outer ambient halo ----
        or_ = 90 * self._outer_scale
        gh = QRadialGradient(cx, cy, or_)
        hc = blend(QColor(0,50,90,int(45*br)), QColor(60,15,0,int(30*br)), aa)
        if ea > 0.05: hc = blend(hc, QColor(70,0,0,40), ea)
        gh.setColorAt(0, hc)
        gh.setColorAt(0.5, QColor(0,15,35,int(15*br)))
        gh.setColorAt(1, QColor(0,0,0,0))
        p.setBrush(QBrush(gh)); p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx-or_, cy-or_, or_*2, or_*2))

        # ---- Layer 6: Holographic scan arcs ----
        if self._scan_alpha > 0.01:
            sa = self._scan_alpha * br
            for ri in [40, 55, 68, 82]:
                p.setPen(QPen(QColor(0,212,255,int(sa*75)), 0.9))
                p.setBrush(Qt.NoBrush)
                arc_r = QRectF(cx-ri, cy-ri, ri*2, ri*2)
                start_a = int(math.degrees(self._scan_ang)*16)
                p.drawArc(arc_r, start_a, int(22*16))

        # ---- Layer 7: Radial tick marks ----
        for i, ang in enumerate(self._tick_ang):
            if i % 4 == 0:   # major
                ri, ro, aw, base_a = 82, 89, 1.2, 150
            else:             # minor
                ri, ro, aw, base_a = 84, 88, 0.6, 70
            a_val = int(base_a * br)
            if self._tick_lit[i]:
                a_val = min(255, a_val + 110)
                c = self._acc_color(a_val)
            else:
                c = QColor(0, 170, 210, a_val)
            p.setPen(QPen(c, aw))
            x1 = cx + ri * math.cos(ang); y1 = cy + ri * math.sin(ang)
            x2 = cx + ro * math.cos(ang); y2 = cy + ro * math.sin(ang)
            p.drawLine(QPointF(x1,y1), QPointF(x2,y2))

        # ---- Layer 4: Mechanical segmented rings ----
        for i, (rr, th, rsp, gaps, ba, rd) in enumerate(self._rings):
            rrs = rr * (self._outer_scale if i >= 5 else 1.0)
            ao  = self._ring_a[i]
            a   = int(ba * br)
            c   = self._ring_color(a, aa, ea)
            pen = QPen(c, th + (0.4 if gaps else 0))
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            if gaps == 0:
                p.drawEllipse(QRectF(cx-rrs, cy-rrs, rrs*2, rrs*2))
            else:
                arc_span = 360.0 / gaps
                draw_arc = arc_span * 0.75
                for g in range(gaps):
                    sd = g * arc_span + math.degrees(ao)
                    p.drawArc(QRectF(cx-rrs, cy-rrs, rrs*2, rrs*2),
                              int(sd*16), int(draw_arc*16))

        # ---- Layer 5: Plasma particles ----
        for part in self._plasma:
            pos = part.pos()
            px, py = cx + pos.x(), cy + pos.y()
            flk = abs(math.sin(t*3 + part.flicker*10))*0.4 + 0.6
            pa  = int(part.alpha * br * flk)
            c   = self._acc_color_plasma(pa, aa, ea)
            gr  = QRadialGradient(px, py, part.size*2)
            gr.setColorAt(0, c)
            gr.setColorAt(1, QColor(c.red(),c.green(),c.blue(),0))
            p.setBrush(QBrush(gr)); p.setPen(Qt.NoPen)
            ps = part.size*2
            p.drawEllipse(QRectF(px-ps, py-ps, ps*2, ps*2))

        # ---- Layer 3: Orbital particles with trails ----
        for part in self._orbitals:
            pos   = part.pos()
            px,py = cx+pos.x(), cy+pos.y()
            flk   = abs(math.sin(t*5 + part.flicker*8))*0.3 + 0.7
            pa    = int(220 * br * flk)
            c_orb = self._orb_color(pa, aa, ea)

            # Trail
            for ti in range(3):
                ta_ang = part.angle - part.speed*self._dt*sp*(ti+1)*4
                tx = cx + part.orbit_r*math.cos(ta_ang)
                ty = cy + part.orbit_r*math.sin(ta_ang)*(1.0 - part.tilt*0.55)
                ta_alpha = int(pa*(0.55 - ti*0.18))
                if ta_alpha <= 0: continue
                tc = QColor(c_orb.red(),c_orb.green(),c_orb.blue(),ta_alpha)
                tps = part.size*(1.0 - ti*0.25)
                tgr = QRadialGradient(tx, ty, tps*2)
                tgr.setColorAt(0, tc); tgr.setColorAt(1, QColor(tc.red(),tc.green(),tc.blue(),0))
                p.setBrush(QBrush(tgr)); p.setPen(Qt.NoPen)
                p.drawEllipse(QRectF(tx-tps, ty-tps, tps*2, tps*2))

            # Main orbital dot
            ps  = part.size*1.5
            pgr = QRadialGradient(px, py, ps*2.5)
            pgr.setColorAt(0, c_orb)
            pgr.setColorAt(0.5, QColor(c_orb.red(),c_orb.green(),c_orb.blue(),int(pa*0.5)))
            pgr.setColorAt(1, QColor(c_orb.red(),c_orb.green(),c_orb.blue(),0))
            p.setBrush(QBrush(pgr)); p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(px-ps, py-ps, ps*2, ps*2))

        # ---- Layer 2: Inner containment rings ----
        for i, (rir, wid, aval) in enumerate([(20,1.0,100),(16,0.6,70)]):
            off = t*(0.4 + i*0.15)*sp*(-1 if i%2 else 1)
            ai  = int(aval * br)
            ci  = self._acc_color(ai)
            ox  = math.sin(off)*1.5; oy = math.cos(off)*1.0
            p.setPen(QPen(ci, wid)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx-rir+ox, cy-rir+oy, rir*2, rir*2))

        # ---- Layer 1: Energy nucleus ----
        nr  = self._nuc_r
        ngr = QRadialGradient(cx, cy, nr*2.5)
        nc0 = QColor(220, 245, 255, int(255*br))
        nc1 = self._acc_color(int(200*br))
        if ea > 0.05:
            nc0 = blend(nc0, QColor(255,80,80,255), ea*0.8)
            nc1 = blend(nc1, QColor(255,40,40,200), ea)
        elif aa > 0.05:
            nc1 = blend(nc1, QColor(255,185,60,200), aa*0.6)
        ngr.setColorAt(0, nc0)
        ngr.setColorAt(0.35, nc1)
        ngr.setColorAt(0.7, QColor(0,50,90,int(110*br)))
        ngr.setColorAt(1, QColor(0,0,0,0))
        p.setBrush(QBrush(ngr)); p.setPen(Qt.NoPen)
        dr = nr*2.5
        p.drawEllipse(QRectF(cx-dr, cy-dr, dr*2, dr*2))

        # Faceted crystalline nucleus polygon
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(t*0.4*sp))
        n6 = 6
        fac_r = nr*0.88
        poly = QPolygonF()
        for i in range(n6):
            ang = i*math.pi*2/n6 + math.pi/n6
            poly.append(QPointF(fac_r*math.cos(ang), fac_r*math.sin(ang)))
        fc_a = int(155*br)
        if ea > 0.05:   fcc = blend(QColor(0,195,235,fc_a), QColor(255,55,55,fc_a), ea)
        elif aa > 0.05: fcc = blend(QColor(0,195,235,fc_a), QColor(255,185,60,fc_a), aa*0.7)
        else:           fcc = QColor(0,195,235,fc_a)
        p.setPen(QPen(fcc, 0.8)); p.setBrush(Qt.NoBrush); p.drawPolygon(poly)
        # Inner hexagon counter-rotating
        p.rotate(-math.degrees(t*0.7*sp))
        ir = nr*0.48
        ipoly = QPolygonF()
        for i in range(n6):
            ang = i*math.pi*2/n6
            ipoly.append(QPointF(ir*math.cos(ang), ir*math.sin(ang)))
        p.setPen(QPen(QColor(225,248,255,int(175*br)), 0.6))
        p.drawPolygon(ipoly)
        p.restore()

        # ---- LISTENING: voice waveform ring ----
        if self._state == ReactorState.LISTENING and self._state_t > 0.1:
            wf_r   = 95
            npts   = 64
            fade   = min(self._state_t, 1.0)
            wave   = QPainterPath()
            for i in range(npts+1):
                ang = i*math.pi*2/npts
                en  = (
                    math.sin(ang*8 + t*12)*3.5 +
                    math.sin(ang*5 - t*9)*2.0 +
                    math.sin(ang*3 + t*6)*1.5
                ) * fade
                rw  = wf_r + en
                wx  = cx + rw*math.cos(ang)
                wy  = cy + rw*math.sin(ang)
                if i == 0: wave.moveTo(wx, wy)
                else:      wave.lineTo(wx, wy)
            wave.closeSubpath()
            p.setPen(QPen(QColor(255,50,50,int(110*fade)), 0.9))
            p.setBrush(Qt.NoBrush)
            p.drawPath(wave)

        # ---- EXECUTING: targeting brackets ----
        if self._state == ReactorState.EXECUTING:
            bsz = 11
            br_ = 74
            for ang_d in [0, 90, 180, 270]:
                ang_r = math.radians(ang_d + t*28*sp)
                bx = cx + br_*math.cos(ang_r)
                by = cy + br_*math.sin(ang_r)
                perp = ang_r + math.pi/2
                p.setPen(QPen(QColor(255,185,60,int(190*br)), 1.5))
                p.drawLine(QPointF(bx,by),
                           QPointF(bx + bsz*math.cos(perp), by + bsz*math.sin(perp)))
                p.drawLine(QPointF(bx,by),
                           QPointF(bx - bsz*math.cos(perp), by - bsz*math.sin(perp)))

        # ---- Offline indicator ----
        if not self._backend_ok:
            p.setPen(QPen(QColor(255,70,70,90), 0.8))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx-93, cy-93, 186, 186))

        p.end()

    # ---- Color helpers -------------------------------------------------------
    def _acc_color(self, a):
        c  = QColor(0, 195, 235, a)
        ea = self._error_aa; aa = self._accent_aa
        if ea > 0.05: return blend(c, QColor(255,40,40,a), ea)
        if aa > 0.05: return blend(c, QColor(255,185,60,a), aa)
        return c

    def _ring_color(self, a, aa, ea):
        c = QColor(0, 195, 235, a)
        if ea > 0.05: return blend(c, QColor(255,40,40,a),  ea)
        if aa > 0.05: return blend(c, QColor(255,185,60,a), aa)
        return c

    def _acc_color_plasma(self, a, aa, ea):
        c = QColor(0, 190, 245, a)
        if ea > 0.05: return blend(c, QColor(255,55,55,a),  ea)
        if aa > 0.05: return blend(c, QColor(255,185,60,a), aa)
        return c

    def _orb_color(self, a, aa, ea):
        c = QColor(170, 235, 255, a)
        if ea > 0.05: return blend(c, QColor(255,100,100,a), ea)
        if aa > 0.05: return blend(c, QColor(255,200,80,a),  aa)
        return c

    # ---- Mouse events -------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            self._drag_moved = False
        event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            self._drag_moved = True
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not getattr(self, "_drag_moved", False):
                # A tap/click without drag → open JARVIS
                self._open_main_jarvis()
            else:
                self._save_position()
            self._drag_pos = None
            self._drag_moved = False

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._open_main_jarvis()

    def contextMenuEvent(self, event):
        CSS = """
            QMenu { background:#0a1520; border:1px solid #006688; color:#a0d8f0;
                    font-family:'Segoe UI'; font-size:10px; padding:4px; }
            QMenu::item { padding:5px 18px; border-radius:2px; }
            QMenu::item:selected { background:#004455; color:#00d4ff; }
            QMenu::separator { height:1px; background:#003344; margin:3px 4px; }
        """
        m = QMenu(self); m.setStyleSheet(CSS)
        ao = m.addAction("Open J.A.R.V.I.S");   m.addSeparator()
        av = m.addAction("Voice");    ast = m.addAction("Settings");  m.addSeparator()
        ax = m.addAction("Exit J.A.R.V.I.S")
        chosen = m.exec_(event.globalPos())
        if chosen == ao:  self._open_main_jarvis()
        elif chosen == av: self._toggle_voice()
        elif chosen == ast: self._open_settings()
        elif chosen == ax: self._quit()

    # ---- Actions ------------------------------------------------------------
    def _pythonw(self):
        """Return the windowless Python interpreter (pythonw.exe) so spawned
        child processes never create a visible console window."""
        exe = sys.executable
        pw = exe.replace("python.exe", "pythonw.exe")
        if os.path.exists(pw):
            return pw
        return exe  # fallback (e.g. on macOS/Linux or unusual installs)

    def _show_companion(self):
        """Show and bring companion to front without stealing focus from other apps."""
        self.show()
        # Re-apply bottom-hint so it stays a desktop companion after show()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnBottomHint |
            Qt.WindowDoesNotAcceptFocus |
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.show()

    def _open_main_jarvis(self):
        """Focus the existing JARVIS window or launch it if not running."""
        try:
            if HAS_REQUESTS:
                try:
                    _req.get(f"{BACKEND_URL}/health", timeout=0.5)
                    # Backend already running — ask it to bring the window forward
                    try:
                        _req.post(f"{BACKEND_URL}/focus", timeout=0.5)
                    except Exception:
                        pass
                    return
                except Exception:
                    pass
            # Backend is not running — launch companion.py windowlessly
            subprocess.Popen(
                [self._pythonw(), COMPANION_SCRIPT],
                close_fds=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                cwd=str(Path(COMPANION_SCRIPT).parent),
            )
        except Exception as e:
            log.error(f"Open JARVIS failed: {e}")

    def _toggle_voice(self):
        if HAS_REQUESTS:
            try:
                _req.post(f"{BACKEND_URL}/toggle_mic", timeout=1.0)
            except Exception:
                pass

    def _open_settings(self):
        self._open_main_jarvis()

    def _restart_companion(self):
        """Restart this companion widget: launch a fresh copy then exit self."""
        log.info("Restarting companion widget...")
        try:
            subprocess.Popen(
                [self._pythonw(), str(Path(__file__).resolve())],
                close_fds=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                cwd=str(Path(__file__).parent),
            )
        except Exception as e:
            log.error(f"Restart failed: {e}")
            return
        # Give the new instance a moment to acquire its mutex before we release ours
        QTimer.singleShot(800, self._quit)

    def _quit(self):
        """Exit the companion widget (and optionally the main JARVIS process)."""
        log.info("Quitting JARVIS widget...")
        # Stop the backend poller thread cleanly
        if hasattr(self, "_poller"):
            self._poller.stop()
            self._poller.wait(800)
        # Remove the tray icon before exiting
        if hasattr(self, "_tray"):
            self._tray.hide()
        # Release the global keyboard hook
        if HAS_KEYBOARD:
            try:
                _kb.unhook_all()
            except Exception:
                pass
        _release_mutex()
        QApplication.quit()


# ---- Entry point ------------------------------------------------------------
def main():
    if not _acquire_mutex():
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("J.A.R.V.I.S Reactor")

    w = JarvisReactorWidget()
    w.show()

    log.info("J.A.R.V.I.S Reactor Widget online.")
    code = app.exec_()
    _release_mutex()
    sys.exit(code)

if __name__ == "__main__":
    main()
