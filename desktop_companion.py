import sys
import json
import os
import requests
import math
from PyQt5.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QAction, QDesktopWidget
from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, pyqtSignal, QObject
from PyQt5.QtGui import QPainter, QColor, QPen, QIcon, QPixmap, QRadialGradient, QTransform

BACKEND_URL = "http://127.0.0.1:8000"
CONFIG_FILE = "companion_config.json"
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

class CompanionState:
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    ERROR = "error"
    OFFLINE = "offline"

# ---------------------------------------------------------
# FRAMEWORK & STATE CONTROLLER
# ---------------------------------------------------------

class BackendPoller(QObject):
    state_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._current_state = CompanionState.OFFLINE
        self._timer = QTimer()
        self._timer.timeout.connect(self.poll)
        self._timer.start(250)
        
    def poll(self):
        try:
            r = requests.get(f"{BACKEND_URL}/status", timeout=0.2)
            if r.status_code == 200:
                new_state = r.json().get("state", CompanionState.IDLE)
            else:
                new_state = CompanionState.ERROR
        except Exception:
            new_state = CompanionState.OFFLINE
            
        if new_state != self._current_state:
            self._current_state = new_state
            self.state_changed.emit(self._current_state)

class BaseEntityWidget(QWidget):
    def __init__(self, name, size=250):
        super().__init__()
        self.name = name
        self.size = size
        self.setFixedSize(size, size)
        
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnBottomHint |
            Qt.WindowDoesNotAcceptFocus |
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        
        self.state = CompanionState.OFFLINE
        self._drag_pos = None
        self._load_position()

    def update_state(self, new_state):
        self.state = new_state
        self.on_state_change()

    def on_state_change(self):
        pass

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = None
            self._save_position()
            event.accept()
            
    def _load_position(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    cfg = json.load(f)
                    pos = cfg.get(self.name)
                    if pos:
                        self.move(pos['x'], pos['y'])
                        return
            except Exception:
                pass
        
        desk = QDesktopWidget().availableGeometry()
        if self.name == "ArcReactor":
            self.move(desk.right() - self.size - 40, desk.bottom() - self.size - 40)
        elif self.name == "ReconDrone":
            self.move(desk.right() - self.size - 40, desk.bottom() - self.size - 300)
        elif self.name == "Helmet":
            self.move(desk.right() - self.size - 300, desk.bottom() - self.size - 40)
        else:
            self.move(desk.center().x() - self.size//2, desk.center().y() - self.size//2)

    def _save_position(self):
        cfg = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    cfg = json.load(f)
            except Exception:
                pass
        cfg[self.name] = {'x': self.x(), 'y': self.y()}
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f)

# ---------------------------------------------------------
# ARC REACTOR ENTITY (Photorealistic)
# ---------------------------------------------------------

class ArcReactorWidget(BaseEntityWidget):
    def __init__(self):
        super().__init__("ArcReactor", size=250)
        self.pixmap = QPixmap(os.path.join(ASSETS_DIR, "arc_reactor.png")).scaled(
            self.size, self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._t = 0.0
        self._intensity = 1.0
        self._target_intensity = 1.0
        
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def on_state_change(self):
        if self.state == CompanionState.IDLE:
            self._target_intensity = 1.0
        elif self.state == CompanionState.LISTENING:
            self._target_intensity = 2.0
        elif self.state == CompanionState.THINKING:
            self._target_intensity = 1.5
        elif self.state == CompanionState.EXECUTING:
            self._target_intensity = 1.2
        elif self.state == CompanionState.ERROR:
            self._target_intensity = 2.0
        else:
            self._target_intensity = 0.5
            
    def _tick(self):
        self._intensity += (self._target_intensity - self._intensity) * 0.1
        self._t += 0.05
        self.update()
        
    def mouseDoubleClickEvent(self, event):
        try:
            requests.post(f"{BACKEND_URL}/focus", timeout=1.0)
        except:
            pass

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # Base Image
        p.drawPixmap(0, 0, self.pixmap)
        
        # Overlay Glows for State
        cx, cy = self.width() / 2, self.height() / 2
        pulse = math.sin(self._t * 2) * 10
        
        if self.state == CompanionState.ERROR:
            color = QColor(255, 0, 0, int(150 * self._intensity))
        elif self.state == CompanionState.EXECUTING:
            color = QColor(255, 150, 0, int(150 * self._intensity))
        else:
            color = QColor(0, 255, 255, int(100 * self._intensity))
            
        p.setCompositionMode(QPainter.CompositionMode_Screen)
        grad = QRadialGradient(cx, cy, 60 + pulse)
        grad.setColorAt(0, color)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 60 + pulse, 60 + pulse)
        
        if self.state == CompanionState.LISTENING:
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.NoBrush)
            r = 70 + pulse
            p.drawEllipse(QPointF(cx, cy), r, r)
            
        p.end()

# ---------------------------------------------------------
# RECON DRONE ENTITY
# ---------------------------------------------------------

class ReconDroneWidget(BaseEntityWidget):
    def __init__(self):
        super().__init__("ReconDrone", size=200)
        self.pixmap = QPixmap(os.path.join(ASSETS_DIR, "recon_drone.png")).scaled(
            self.size, self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._t = 0.0
        self._hover_y = 0.0
        self._target_hover = 0.0
        
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def _tick(self):
        self._t += 0.05
        if self.state == CompanionState.IDLE:
            self._target_hover = math.sin(self._t) * 15
        elif self.state == CompanionState.THINKING:
            self._target_hover = math.sin(self._t * 3) * 5
        elif self.state == CompanionState.LISTENING:
            self._target_hover = 0
            
        self._hover_y += (self._target_hover - self._hover_y) * 0.1
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        
        cx, cy = self.width() / 2, self.height() / 2
        
        # Scanning Beam behind the drone
        if self.state in (CompanionState.EXECUTING, CompanionState.THINKING):
            p.setCompositionMode(QPainter.CompositionMode_Screen)
            grad = QRadialGradient(cx, cy + self._hover_y, 100)
            grad.setColorAt(0, QColor(0, 200, 255, 80))
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(grad)
            p.setPen(Qt.NoPen)
            p.drawPie(int(cx - 100), int(cy + self._hover_y), 200, 200, int(-45 * 16), int(-90 * 16))
            
        # Draw drone
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.drawPixmap(0, int(self._hover_y), self.pixmap)
        
        # Eye glow
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        eye_color = QColor(0, 255, 255, 150)
        if self.state == CompanionState.ERROR:
            eye_color = QColor(255, 50, 50, 200)
        elif self.state == CompanionState.EXECUTING:
            eye_color = QColor(255, 150, 0, 200)
            
        pulse = math.sin(self._t * 5) * 5 if self.state != CompanionState.IDLE else 0
        grad_eye = QRadialGradient(cx, cy + self._hover_y + 10, 20 + pulse)
        grad_eye.setColorAt(0, eye_color)
        grad_eye.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(grad_eye)
        p.drawEllipse(QPointF(cx, cy + self._hover_y + 10), 20 + pulse, 20 + pulse)
        p.end()

# ---------------------------------------------------------
# HOLOGRAPHIC HELMET ENTITY
# ---------------------------------------------------------

class HelmetWidget(BaseEntityWidget):
    def __init__(self):
        super().__init__("Helmet", size=250)
        self.pixmap = QPixmap(os.path.join(ASSETS_DIR, "helmet.png")).scaled(
            self.size, self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._t = 0.0
        self._alpha = 0.0
        self._target_alpha = 0.0
        
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)
        
        # Ensure it starts fully hidden
        self.hide()

    def on_state_change(self):
        # Helmet manifests temporarily on Major Events
        if self.state in (CompanionState.SPEAKING, CompanionState.ERROR):
            self._target_alpha = 1.0
            if self.isHidden():
                self.show()
        else:
            self._target_alpha = 0.0

    def _tick(self):
        self._t += 0.05
        self._alpha += (self._target_alpha - self._alpha) * 0.1
        if self._alpha < 0.01 and self._target_alpha == 0:
            if not self.isHidden():
                self.hide()
        else:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # Glitch / Hologram transparency
        p.setOpacity(self._alpha)
        
        offset_y = math.sin(self._t) * 5
        p.drawPixmap(0, int(offset_y), self.pixmap)
        
        if self.state == CompanionState.ERROR:
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            p.setOpacity(self._alpha * 0.5)
            p.fillRect(self.rect(), QColor(255, 0, 0))
            
        p.end()

# ---------------------------------------------------------
# COMPANION APP CONTROLLER
# ---------------------------------------------------------

class DesktopCompanionApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        
        self.poller = BackendPoller()
        self.entities = [
            ArcReactorWidget(),
            ReconDroneWidget(),
            HelmetWidget()
        ]
        
        for entity in self.entities:
            self.poller.state_changed.connect(entity.update_state)
            if entity.name != "Helmet":
                entity.show()
            
        self._setup_tray()
        
    def _setup_tray(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(0, 200, 255))
        p.setPen(Qt.NoPen)
        p.drawEllipse(16, 16, 32, 32)
        p.end()
        
        self.tray = QSystemTrayIcon(QIcon(pixmap), self.app)
        self.menu = QMenu()
        
        show_action = QAction("Focus JARVIS", self.app)
        show_action.triggered.connect(self._focus_backend)
        
        quit_action = QAction("Exit Companion", self.app)
        quit_action.triggered.connect(self.app.quit)
        
        self.menu.addAction(show_action)
        self.menu.addSeparator()
        self.menu.addAction(quit_action)
        
        self.tray.setContextMenu(self.menu)
        self.tray.show()
        
    def _focus_backend(self):
        try:
            requests.post(f"{BACKEND_URL}/focus", timeout=1.0)
        except:
            pass
            
    def run(self):
        sys.exit(self.app.exec_())

def single_instance_lock():
    import ctypes
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "JarvisP1_DesktopCompanion_Mutex")
    if ctypes.windll.kernel32.GetLastError() == 183:
        sys.exit(0)
    return mutex

if __name__ == "__main__":
    _mtx = single_instance_lock()
    companion = DesktopCompanionApp()
    companion.run()
