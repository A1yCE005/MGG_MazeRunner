# -*- coding: utf-8 -*-
import os
import sys
import json
import threading
import traceback
import time  # Added


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QSlider, QLineEdit, QFileDialog,
    QCheckBox, QTabWidget, QDialog, QListWidget, QListWidgetItem
)

from maze_core import MazeBot

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def _load_config() -> dict:
    cfg = {
        "title": "マブラヴ：ガールズガーデンX",
        "templates_dir": os.path.join(os.path.dirname(__file__), "templates"),
        "thr_main": 0.76,
        "thr_tag": 0.77,
        "thr_skip_color": 0.64,
        "sleep_base": 0.03,
        "sleep_fast": 0.02,
        "route_left_ratio": 0.56,
        "event_priority": "event_risky,event_battle,event_support,event_shop,event_event,event_unknown",
        "hotkey_start": "f4",
        "hotkey_stop": "f3",
        "debug": True,
        "low_power": False
    }
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data or {})
    except Exception:
        pass
    return cfg

def _save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ---------- Method A: Window picker ----------
class WindowPickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择窗口")
        self.resize(720, 520)
        lay = QVBoxLayout(self)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索窗口标题…")
        lay.addWidget(self.search)

        self.listw = QListWidget(self)
        lay.addWidget(self.listw, 1)

        row = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        lay.addLayout(row)

        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        self.listw.itemDoubleClicked.connect(lambda *_: self.accept())
        self.search.textChanged.connect(self._render)

        self.titles = self._load_titles()
        self._render()

    def _load_titles(self):
        import pygetwindow as gw
        seen, titles = set(), []
        for t in gw.getAllTitles():
            t = (t or "").strip()
            if not t or t in seen:
                continue
            seen.add(t)
            titles.append(t)
        titles.sort(key=lambda s: (-len(s), s.lower()))
        return titles

    def _render(self):
        key = self.search.text().strip().lower()
        self.listw.clear()
        for t in self.titles:
            if key and key not in t.lower():
                continue
            self.listw.addItem(QListWidgetItem(t))

    def selected_title(self) -> str:
        it = self.listw.currentItem()
        return it.text().strip() if it else ""

# ---------- Hotkey capture input ----------
class KeyCaptureLineEdit(QLineEdit):
    keyChanged = Signal(str)

    _name_map = {
        Qt.Key_Space: "space", Qt.Key_Tab: "tab", Qt.Key_Backspace: "backspace",
        Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Escape: "esc",
        Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
        Qt.Key_Home: "home", Qt.Key_End: "end", Qt.Key_PageUp: "page up", Qt.Key_PageDown: "page down",
        Qt.Key_Insert: "insert", Qt.Key_Delete: "delete",
    }
    _sym_map = {
        Qt.Key_Minus: "-", Qt.Key_Equal: "=", Qt.Key_Comma: ",", Qt.Key_Period: ".",
        Qt.Key_Slash: "/", Qt.Key_Backslash: "\\",
        Qt.Key_Semicolon: ";", Qt.Key_Apostrophe: "'",
        Qt.Key_BracketLeft: "[", Qt.Key_BracketRight: "]",
        getattr(Qt, "Key_QuoteLeft", getattr(Qt, "Key_AsciiTilde", 0)): "`",
    }

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setPlaceholderText("点击此处，然后按组合键…（Esc 取消，Backspace 清空）")

    def keyPressEvent(self, e: QKeyEvent):
        k = e.key()
        if k == Qt.Key_Escape:
            self.clearFocus()
            return
        if k in (Qt.Key_Backspace, Qt.Key_Delete):
            self.setText("")
            self.keyChanged.emit("")
            return
        if k in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return

        mods = []
        if e.modifiers() & Qt.ControlModifier:
            mods.append("ctrl")
        if e.modifiers() & Qt.ShiftModifier:
            mods.append("shift")
        if e.modifiers() & Qt.AltModifier:
            mods.append("alt")
        if e.modifiers() & Qt.MetaModifier:
            mods.append("win")

        if Qt.Key_F1 <= k <= Qt.Key_F24:
            key_name = f"f{k - Qt.Key_F1 + 1}"
        elif Qt.Key_A <= k <= Qt.Key_Z:
            key_name = chr(k).lower()
        elif Qt.Key_0 <= k <= Qt.Key_9:
            key_name = chr(k)
        elif k in self._name_map:
            key_name = self._name_map[k]
        elif k in self._sym_map:
            key_name = self._sym_map[k]
        else:
            ch = (e.text() or "").strip()
            key_name = ch.lower() if ch else ""
            if not key_name:
                try:
                    key_name = chr(k).lower()
                    if not key_name.isprintable():
                        key_name = ""
                except Exception:
                    key_name = ""

        if not key_name:
            return
        combo = "+".join(mods + [key_name]) if mods else key_name
        self.setText(combo)
        self.keyChanged.emit(combo)
        self.clearFocus()

# ---------- Main window ----------
class BotWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Maze Runner Bot")
        self.resize(980, 640)  # Slightly smaller

        # Unified font
        fam = self._pick_font_family()
        app_font = QFont(fam, 11)
        QApplication.instance().setFont(app_font)

        self.setStyleSheet("""
        QWidget { font-size: 11pt; }
        QLineEdit { height: 32px; }
        QPushButton { height: 34px; padding: 6px 12px; }
        QSlider::groove:horizontal { height: 8px; background:#5b5b5b; border-radius:4px; }
        QSlider::handle:horizontal { background:#d0d0d0; border:1px solid #888; width:18px; height:18px; margin:-6px 0; border-radius:9px; }
        QSlider::add-page:horizontal { background:#6a6a6a; }
        QSlider::sub-page:horizontal { background:#7a7a7a; }
        """)

        self.cfg = _load_config()
        self._build_ui()
        self._register_hotkeys()

        self.bot: MazeBot | None = None
        self.bot_thread: threading.Thread | None = None
        self._running = False

        self.log("[DEBUG] Loaded config from: " + CONFIG_PATH)

    def _on_export_logs(self):
        """导出日志到 txt 文件"""
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            default_name = os.path.join(os.path.expanduser("~"), f"maze_log_{ts}.txt")
            fn, _ = QFileDialog.getSaveFileName(self, "导出日志为…", default_name, "文本文件 (*.txt)")
            if not fn:
                return
            with open(fn, "w", encoding="utf-8") as f:
                f.write(self.log_view.toPlainText())
            self.log(f"[INFO] 已导出日志到: {fn}")
        except Exception as e:
            self.log(f"[ERR] 导出日志失败: {e}")


    def _pick_font_family(self) -> str:
        db = QFontDatabase()
        prefer = ["Microsoft YaHei UI", "Meiryo UI", "Segoe UI", "Microsoft YaHei", "Meiryo"]
        installed = set(db.families())
        for f in prefer:
            if f in installed:
                return f
        return QApplication.font().family()

    # ---------- UI ----------
    def _build_ui(self):
        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.North)
        self.setCentralWidget(tabs)

        self.ctrl_page = QWidget()
        tabs.addTab(self.ctrl_page, "控制台")
        self._build_console_tab(self.ctrl_page)

        self.set_page = QWidget()
        tabs.addTab(self.set_page, "设置")
        self._build_settings_tab(self.set_page)

    def _build_console_tab(self, page: QWidget):
        main = QVBoxLayout(page)

        row0 = QHBoxLayout()
        row0.addWidget(QLabel("窗口标题"))
        self.title_edit = QLineEdit(self.cfg.get("title", ""))
        row0.addWidget(self.title_edit, 1)
        self.btn_pick = QPushButton("选择窗口")
        self.btn_pick.clicked.connect(self._pick_window)
        row0.addWidget(self.btn_pick)
        main.addLayout(row0)

        def add_slider(label, key, minv, maxv, step, factor=100):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            sl = QSlider(Qt.Horizontal)
            sl.setMinimum(int(minv * factor))
            sl.setMaximum(int(maxv * factor))
            sl.setSingleStep(int(step * factor))
            sl.setPageStep(int(step * factor))
            val = float(self.cfg.get(key, minv))
            sl.setValue(int(val * factor))
            lab = QLineEdit(f"{val:.2f}")
            lab.setFixedWidth(80)
            def _on_change(v):
                x = v / factor
                self.cfg[key] = x
                lab.setText(f"{x:.2f}")
                _save_config(self.cfg)
            sl.valueChanged.connect(_on_change)
            row.addWidget(sl, 1)
            row.addWidget(lab)
            main.addLayout(row)
            return sl, lab

        self.s_thr_main, _ = add_slider("thr_main", "thr_main", 0.50, 0.95, 0.01)
        self.s_thr_tag, _ = add_slider("thr_tag", "thr_tag", 0.50, 0.95, 0.01)
        self.s_thr_skip, _ = add_slider("thr_skip_color", "thr_skip_color", 0.50, 0.95, 0.01)
        self.s_sleep_base, _ = add_slider("sleep_base (s)", "sleep_base", 0.01, 0.10, 0.001, factor=1000)
        self.s_sleep_fast, _ = add_slider("sleep_fast (s)", "sleep_fast", 0.005, 0.08, 0.001, factor=1000)
        self.s_route_left, _ = add_slider("route_left_ratio", "route_left_ratio", 0.30, 0.80, 0.01)

        row_btn = QHBoxLayout()
        self.btn_start = QPushButton("启动")
        self.btn_stop = QPushButton("停止")
        self.btn_start.clicked.connect(self._on_click_start)
        self.btn_stop.clicked.connect(self._on_click_stop)
        row_btn.addWidget(self.btn_start)
        row_btn.addWidget(self.btn_stop)
        row_btn = QHBoxLayout()
        self.btn_start = QPushButton("启动")
        self.btn_stop = QPushButton("停止")
        self.btn_start.clicked.connect(self._on_click_start)
        self.btn_stop.clicked.connect(self._on_click_stop)
        row_btn.addWidget(self.btn_start)
        row_btn.addWidget(self.btn_stop)

        # >>> Added: export log button
        self.btn_export = QPushButton("导出日志…")
        self.btn_export.clicked.connect(self._on_export_logs)
        row_btn.addWidget(self.btn_export)
        # <<< End of addition

        main.addLayout(row_btn)

        main.addLayout(row_btn)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        f = QFont(QApplication.font().family(), 10)
        self.log_view.setFont(f)
        main.addWidget(self.log_view, 1)

    def _build_settings_tab(self, page: QWidget):
        main = QVBoxLayout(page)

        row_tpl = QHBoxLayout()
        row_tpl.addWidget(QLabel("模板目录"))
        self.tpl_edit = QLineEdit(self.cfg.get("templates_dir", ""))
        row_tpl.addWidget(self.tpl_edit, 1)
        btn_browse = QPushButton("浏览…")
        def _pick_dir():
            d = QFileDialog.getExistingDirectory(self, "选择模板目录", self.tpl_edit.text() or os.getcwd())
            if d:
                self.tpl_edit.setText(d)
                self.cfg["templates_dir"] = d
                _save_config(self.cfg)
        btn_browse.clicked.connect(_pick_dir)
        row_tpl.addWidget(btn_browse)
        main.addLayout(row_tpl)

        row_pr = QHBoxLayout()
        row_pr.addWidget(QLabel("事件优先级（逗号分隔）"))
        self.priority_edit = QLineEdit(self.cfg.get(
            "event_priority",
            "event_risky,event_battle,event_support,event_shop,event_event,event_unknown"))
        row_pr.addWidget(self.priority_edit, 1)
        self.priority_edit.editingFinished.connect(self._save_priority)
        main.addLayout(row_pr)

        row_opt = QHBoxLayout()
        self.chk_debug = QCheckBox("调试模式（输出详细日志）")
        self.chk_debug.setChecked(bool(self.cfg.get("debug", True)))
        self.chk_debug.stateChanged.connect(self._on_debug_changed)
        row_opt.addWidget(self.chk_debug)

        self.chk_low = QCheckBox("低功耗（偏保守路线）")
        self.chk_low.setChecked(bool(self.cfg.get("low_power", False)))
        self.chk_low.stateChanged.connect(self._on_low_power_changed)
        row_opt.addWidget(self.chk_low)

        row_opt.addStretch(1)
        main.addLayout(row_opt)

        row_hk1 = QHBoxLayout()
        row_hk1.addWidget(QLabel("开始快捷键"))
        self.hk_start_edit = KeyCaptureLineEdit(self.cfg.get("hotkey_start", "f4"))
        self.hk_start_edit.keyChanged.connect(lambda s: self._set_hotkey("hotkey_start", s))
        row_hk1.addWidget(self.hk_start_edit, 1)
        main.addLayout(row_hk1)

        row_hk2 = QHBoxLayout()
        row_hk2.addWidget(QLabel("停止快捷键"))
        self.hk_stop_edit = KeyCaptureLineEdit(self.cfg.get("hotkey_stop", "f3"))
        self.hk_stop_edit.keyChanged.connect(lambda s: self._set_hotkey("hotkey_stop", s))
        row_hk2.addWidget(self.hk_stop_edit, 1)
        main.addLayout(row_hk2)

        main.addStretch(1)

    # ---------- Config callbacks ----------
    def _pick_window(self):
        dlg = WindowPickerDialog(self)
        if dlg.exec():
            t = dlg.selected_title()
            if t:
                self.title_edit.setText(t)
                self.cfg["title"] = t
                _save_config(self.cfg)
                self.log(f"[DEBUG] Bound: {t}")

    def _save_priority(self):
        self.cfg["event_priority"] = self.priority_edit.text().strip()
        _save_config(self.cfg)

    def _on_debug_changed(self):
        self.cfg["debug"] = self.chk_debug.isChecked()
        _save_config(self.cfg)

    def _on_low_power_changed(self):
        self.cfg["low_power"] = self.chk_low.isChecked()
        _save_config(self.cfg)

    def _set_hotkey(self, key_name: str, hotkey: str):
        self.cfg[key_name] = hotkey.strip()
        _save_config(self.cfg)
        self._register_hotkeys()

    def _param_provider(self) -> dict:
        cfg = dict(self.cfg)
        cfg["title"] = self.title_edit.text().strip() or cfg.get("title", "")
        cfg["templates_dir"] = self.tpl_edit.text().strip() or cfg.get("templates_dir")
        if cfg.get("low_power", False):
            cfg["sleep_base"] = float(cfg.get("sleep_base", 0.03)) * 1.5
            cfg["sleep_fast"] = float(cfg.get("sleep_fast", 0.02)) * 1.5
        return cfg

    # ---------- Start & stop ----------
    def _on_click_start(self):
        if self._running:
            return
        try:
            self._start_bot()
        except Exception as e:
            self.log(f"[ERR] {e}\n{traceback.format_exc()}")

    def _on_click_stop(self):
        if not self._running:
            return
        try:
            if self.bot:
                self.bot.stop()
            self._running = False
        except Exception as e:
            self.log(f"[ERR] {e}")

    def _start_bot(self):
        self.cfg["title"] = self.title_edit.text().strip()
        self.cfg["templates_dir"] = self.tpl_edit.text().strip() or self.cfg.get("templates_dir")
        _save_config(self.cfg)

        def _logger(msg: str):
            self.log(msg)

        self.bot = MazeBot(
            hwnd_title=self.cfg["title"],
            templates_dir=self.cfg.get("templates_dir"),
            log=_logger,
            param_provider=self._param_provider,
            debug=self.cfg.get("debug", True),
        )
        self.bot.start()

        # Only enter one loop; the rest is internal
        self.bot_thread = threading.Thread(target=self._run_loop_once, daemon=True)
        self.bot_thread.start()
        self._running = True

    def _run_loop_once(self):
        try:
            self.bot.loop()
        except Exception as e:
            self.log(f"[ERR] {e}\n{traceback.format_exc()}")
            self._running = False

    # ---------- Logs & hotkeys ----------
    def log(self, s: str):
        self.log_view.append(s)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _register_hotkeys(self):
        try:
            import keyboard
        except Exception as e:
            self.log(f"[WARN] 键盘热键不可用: {e}")
            return
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

        start = self.cfg.get("hotkey_start", "").strip()
        stop = self.cfg.get("hotkey_stop", "").strip()

        try:
            if start:
                keyboard.add_hotkey(start, lambda: self._on_click_start())
            if stop:
                keyboard.add_hotkey(stop, lambda: self._on_click_stop())
            if start or stop:
                self.log(f"[INFO] 热键就绪：启动[{start or '未设置'}] / 停止[{stop or '未设置'}]")
        except Exception as e:
            self.log(f"[ERR] 注册热键失败：{e}")

    def closeEvent(self, e):
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            if self.bot:
                self.bot.stop()
        except Exception:
            pass
        return super().closeEvent(e)

def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    app = QApplication(sys.argv)
    w = BotWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
