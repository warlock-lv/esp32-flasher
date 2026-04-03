# -*- coding: utf-8 -*-
"""
ESP32 固件烧录工具 — PyQt6 版
功能与 esp32-flash-tool/app.py（Tkinter）对齐；界面缩放与大量日志表现更好。
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time

from PyQt6.QtCore import QFileInfo, QObject, QPoint, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QFontMetrics, QIcon, QGuiApplication, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFileIconProvider,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    import serial
    import serial.tools.list_ports

    list_ports = serial.tools.list_ports

try:
    import esptool  # noqa: F401
except ImportError:
    esptool = None


def _runtime_project_dir() -> str:
    """项目根目录：源码运行为脚本目录；PyInstaller onefile 为 exe 所在目录（勿用 __file__，否则落在临时目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _app_icon_search_roots() -> list[str]:
    """图标查找目录：exe/脚本目录 + PyInstaller onefile 解压目录（_MEIPASS）。"""
    roots: list[str] = []
    rd = _runtime_project_dir()
    if rd:
        roots.append(rd)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and isinstance(meipass, str) and os.path.isdir(meipass):
            roots.append(meipass)
    return roots


def _icon_has_decodable_pixmap(ic: QIcon) -> bool:
    """部分 ICO 仅含 16×16 等尺寸，单独测 32×32 会得到空图误判为无效。"""
    for size in (16, 24, 32, 48, 64, 128, 256):
        if not ic.pixmap(size, size).isNull():
            return True
    return False


def _load_working_app_icon() -> QIcon:
    """依次尝试常见文件名，仅返回 Qt 能实际解码的非空 QIcon（避免无效 ico 覆盖 exe 内嵌图标）。"""
    names = ("app_exe.ico", "app.ico", "icon.ico", "app.png", "icon.png")
    for root in _app_icon_search_roots():
        for name in names:
            p = os.path.join(root, name)
            if not os.path.isfile(p):
                continue
            try:
                ic = QIcon(p)
            except Exception:
                ic = QIcon()
            if not ic.isNull() and _icon_has_decodable_pixmap(ic):
                return ic
            try:
                pm = QPixmap(p)
            except Exception:
                pm = QPixmap()
            if not pm.isNull():
                return QIcon(pm)
    return QIcon()


def _icon_from_frozen_executable() -> QIcon:
    """Windows 下从已打包 exe 取 Shell 图标（与 --icon 嵌入一致）；须在 QApplication 创建后调用。"""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return QIcon()
    exe = os.path.abspath(sys.executable)
    if not os.path.isfile(exe):
        return QIcon()
    try:
        ic = QFileIconProvider().icon(QFileInfo(exe))
    except Exception:
        return QIcon()
    if ic.isNull() or not _icon_has_decodable_pixmap(ic):
        return QIcon()
    return ic


def _resolve_app_icon() -> QIcon:
    """优先磁盘图标文件，失败时在 frozen+Windows 下回退为 exe 内嵌图标。"""
    ic = _load_working_app_icon()
    if not ic.isNull():
        return ic
    return _icon_from_frozen_executable()


# PyInstaller 打包后 sys.executable 是本程序的 .exe。若仍用 [sys.executable, "-m", "esptool"]，
# 子进程会再次启动同一 GUI 入口，从而出现第二个主窗体。frozen 下改为专用参数分支只执行 esptool。
_ESPTOOL_SUBPROC_FLAG = "__ESP32_PYQT_ESPTOOL__"


def _run_esptool_cli_only() -> None:
    """供子进程调用：仅执行 esptool，不创建 Qt 主窗体。"""
    import esptool as _esptool_mod

    sys.argv = ["esptool"] + sys.argv[2:]
    _esptool_mod._main()


def _format_esptool_exit_error(rc: int, lines: list[str]) -> str:
    """esptool 非零退出码时，附带控制台末尾输出，便于导出记录里看到具体原因。"""
    tail = [ln.rstrip() for ln in lines[-20:] if str(ln).strip()]
    body = "\n".join(tail)
    if len(body) > 2000:
        body = "…\n" + body[-2000:]
    if body.strip():
        return f"esptool exited with code {rc}. 最近输出:\n{body.strip()}"
    return f"esptool exited with code {rc} (无控制台输出)"


# ---------------------------------------------------------------------------
# 深色主题（参考暗色工具界面：主底深灰蓝、输入区更深、无白底）
COLORS = {
    "bg_main": "#2C3844",
    "bg_panel": "#252f38",
    "bg_input": "#161b22",
    "text_primary": "#e6edf3",
    "text_secondary": "#adbac7",
    "primary": "#58a6ff",
    "success": "#3fb950",
    "danger": "#f85149",
    "info": "#5a9cf8",
    "muted": "#768390",
    "border": "#3d4f5c",
    # 串口列表 / 固件设置 / 烧录统计 / 烧录设置 / 运行日志 等 QGroupBox 外框
    "group_border": "#4d5f0c",
    "accent_green": "#2ecc71",
    "accent_green_hover": "#27ae60",
}

FONT_PT = 13
FONT_LOG_PT = 12
FONT_FAMILY = "Microsoft YaHei UI"
FONT_LOG_FAMILY = "Consolas"

# 与固件路径 QLineEdit 行高一致（见 _build_ui 中 row_h）
BUTTON_ROW_H = 36
# PORT8 等标签需略宽于「#8」列宽，避免末位数字被裁切
PORT_LABEL_W = 64


def polish_pushbutton(btn: QPushButton, row_h: int = BUTTON_ROW_H) -> None:
    """关闭 Windows 默认按钮绘制，否则常只剩彩色边框、中间不填充（与是否缓存无关）。"""
    if btn is None:
        return
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFlat(False)
    try:
        btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    except Exception:
        pass

    # 竖排「刷新端口」多行文字，不设固定行高，避免与单行输入框高度策略冲突
    is_refresh_vertical = btn.objectName() == "refreshPortBtn"
    # 除“刷新端口”外的按钮整体高度比固件路径框低 4px
    other_btn_h = row_h - 10
    refresh_h = btn.minimumHeight() if is_refresh_vertical else 0

    # 直接给按钮实例挂样式，避免主窗口里某些 QPushButton 被底层样式引擎“部分覆盖”
    # 目标效果：实心亮绿底 + 深色字 + hover/pressed 反馈；单行按钮高度与固件路径行一致。
    try:
        if not is_refresh_vertical:
            btn.setFixedHeight(other_btn_h)
        _mh = f"max-height: {other_btn_h}px;" if not is_refresh_vertical else ""

        # 刷新端口按钮的样式里不要用固定的 1.2em min-height，否则 setMinimumHeight 调大可能看起来不生效
        refresh_min_h_css = f"{refresh_h}px" if is_refresh_vertical and refresh_h > 0 else "1.2em"
        refresh_max_h_css = f"max-height: {refresh_h}px;" if is_refresh_vertical and refresh_h > 0 else ""
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS['accent_green']};
                color: #0d1117;
                border: none;
                border-radius: 5px;
                font-weight: bold;
                padding: {'4px 6px' if is_refresh_vertical else '4px 12px'};
                min-height: {refresh_min_h_css if is_refresh_vertical else f'{other_btn_h}px'};
                {refresh_max_h_css}
                {_mh}
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_green_hover']};
            }}
            QPushButton:pressed {{
                background-color: #1e8449;
                padding: {'3px 5px' if is_refresh_vertical else '3px 12px'};
            }}
            QPushButton:disabled {{
                background-color: #2d4a38;
                color: #6b7a72;
                border: none;
            }}
            """
        )
    except Exception:
        pass


def app_stylesheet() -> str:
    c = COLORS
    return f"""
    QMainWindow, QDialog {{
        background-color: {c["bg_main"]};
        color: {c["text_primary"]};
    }}
    /* 不要对 QWidget 统一设透明背景：QPushButton 也是 QWidget，会导致主窗体里按钮无法显示实心绿底 */
    QWidget {{
        color: {c["text_primary"]};
    }}
    QGroupBox {{
        font-weight: bold;
        border: 1px solid {c["group_border"]};
        border-radius: 6px;
        margin-top: 14px;
        padding-top: 8px;
        padding-bottom: 6px;
        background-color: {c["bg_panel"]};
        color: {c["text_primary"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }}
    QLabel {{
        color: {c["text_primary"]};
        background: transparent;
    }}
    QLineEdit {{
        background-color: {c["bg_input"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: 5px;
        padding: 6px 10px;
        selection-background-color: {c["primary"]};
        selection-color: #ffffff;
    }}
    QLineEdit:read-only {{
        background-color: {c["bg_input"]};
        color: {c["text_secondary"]};
    }}
    QPlainTextEdit {{
        background-color: {c["bg_input"]};
        color: {c["text_secondary"]};
        border: 1px solid {c["border"]};
        border-radius: 5px;
        padding: 6px 8px;
        selection-background-color: {c["primary"]};
        selection-color: #ffffff;
    }}
    QComboBox {{
        background-color: {c["bg_input"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: 5px;
        padding: 1px 12px;
        min-height: 1.2em;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c["bg_input"]};
        color: {c["text_primary"]};
        selection-background-color: {c["primary"]};
        selection-color: #ffffff;
        border: 1px solid {c["border"]};
        outline: none;
    }}
    /* 实心绿底：border 用 none，避免只画出边框线；配合 polish_pushbutton 关闭 autoDefault */
    QPushButton {{
        background-color: {c["accent_green"]};
        color: #0d1117;
        border: none;
        border-radius: 5px;
        padding: 4px 12px;
        font-weight: bold;
        outline: none;
    }}
    QPushButton:hover {{
        background-color: {c["accent_green_hover"]};
    }}
    QPushButton:pressed {{
        background-color: #1e8449;
        padding-top: 5px;
        padding-bottom: 3px;
        padding-left: 13px;
        padding-right: 11px;
    }}
    QPushButton:disabled {{
        background-color: #2d4a38;
        color: #6b7a72;
    }}
    QGroupBox QPushButton {{
        background-color: {c["accent_green"]};
        color: #0d1117;
        border: none;
    }}
    QCheckBox {{
        color: {c["text_primary"]};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 17px;
        height: 17px;
        border-radius: 3px;
        border: 1px solid {c["border"]};
        background-color: {c["bg_input"]};
    }}
    QCheckBox::indicator:checked {{
        background-color: {c["primary"]};
        border-color: {c["primary"]};
    }}
    QPlainTextEdit#mainLogList {{
        /* 主窗口运行日志：无边框（通用 QPlainTextEdit 样式仍生效） */
        border: none;
    }}
    QScrollBar:vertical {{
        background: {c["bg_panel"]};
        width: 10px;
        margin: 2px 0;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {c["border"]};
        min-height: 28px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
        width: 0;
    }}
    QScrollBar:horizontal {{
        background: {c["bg_panel"]};
        height: 10px;
        margin: 0 2px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c["border"]};
        min-width: 28px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        height: 0;
        width: 0;
    }}
    """


def _check_deps() -> bool:
    try:
        import serial  # noqa
        import esptool  # noqa
        return True
    except ImportError as e:
        QMessageBox.critical(None, "依赖错误", f"缺少依赖: {e}\n请执行: pip install -r requirements.txt")
        return False


class PortLogDialog(QDialog):
    """单端口 esptool 输出（主线程创建）。"""

    MAX_LINES = 8000

    def __init__(self, parent: QWidget, port: str, on_close=None):
        super().__init__(parent)
        self.setWindowTitle(f"端口 {port} 烧录日志")
        self.resize(760, 520)
        self._on_close = on_close

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        bar.addWidget(QLabel(f"端口: {port}"))
        bar.addStretch()
        btn_clear = QPushButton("清除日志")
        polish_pushbutton(btn_clear)
        btn_clear.clicked.connect(self._clear)
        bar.addWidget(btn_clear)
        lay.addLayout(bar)

        # QPlainTextEdit 只读：可拖选、Ctrl+C 复制；QListWidget 逐行复制体验差
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setUndoRedoEnabled(False)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setFont(QFont(FONT_LOG_FAMILY, FONT_LOG_PT))
        lay.addWidget(self.log_text)

    def append_line(self, text: str):
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
        self.log_text.insertPlainText(text + "\n")
        lines = self.log_text.toPlainText().splitlines()
        if len(lines) > self.MAX_LINES:
            self.log_text.setPlainText("\n".join(lines[-self.MAX_LINES :]) + "\n")
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())
        cur = self.log_text.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cur)

    def _clear(self):
        self.log_text.clear()

    def closeEvent(self, event):
        if callable(self._on_close):
            try:
                self._on_close()
            except Exception:
                pass
        super().closeEvent(event)


class FlashSignals(QObject):
    """工作线程 -> 主线程 UI 更新（线程安全）。"""

    main_log = pyqtSignal(str)
    sub_log = pyqtSignal(str, str)  # port, line
    create_log_dialog = pyqtSignal(str)
    log_dialog_ready = pyqtSignal(str)
    port_status = pyqtSignal(int, str, str)  # slot, kind, text
    stats_update = pyqtSignal()
    ports_changed = pyqtSignal(object, object)  # old set, new set


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESP批量烧录")
        self._try_set_window_icon()
        self.setMinimumSize(1020, 880)
        self.resize(1020, 880)
        self.move(0, 0)

        self._config_path = os.path.join(_runtime_project_dir(), "config.json")

        self.log_windows: dict[str, PortLogDialog] = {}
        # 烧录日志子窗体打开顺序（用于第 2 个起相对上一个做左/下偏移）
        self._log_dialog_order: list[str] = []
        self.flash_cancel_events: dict[str, threading.Event] = {}
        self.flash_processes: dict[str, subprocess.Popen] = {}
        self._log_dialog_events: dict[str, threading.Event] = {}

        self._signals = FlashSignals()
        self._signals.main_log.connect(self._append_main_log)
        self._signals.sub_log.connect(self._on_sub_log)
        self._signals.create_log_dialog.connect(self._slot_create_log_dialog)
        self._signals.port_status.connect(self._slot_port_status)
        self._signals.stats_update.connect(self._slot_stats)
        self._signals.ports_changed.connect(self._handle_port_changes)

        self._last_port_slots = [""] * 8

        self.flash_records: list[dict] = []
        self.flash_success_count = 0
        self.flash_fail_count = 0
        self.flash_total_count = 0

        self._max_main_log_lines = 2000

        self._build_ui()
        self._signals.log_dialog_ready.connect(self._mark_log_ready)

        QTimer.singleShot(80, self._delayed_init)

    def _try_set_window_icon(self) -> None:
        """尝试加载图标；含 exe 内嵌回退（Windows frozen）。"""
        ic = _resolve_app_icon()
        if not ic.isNull():
            self.setWindowIcon(ic)

    def _mark_log_ready(self, port: str):
        ev = self._log_dialog_events.get(port)
        if ev:
            ev.set()

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background-color: {COLORS['bg_main']};")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(14)
        root.setContentsMargins(16, 16, 16, 16)

        top = QHBoxLayout()
        top.setSpacing(12)
        root.addLayout(top, stretch=0)

        # 与固件区行距、行高一致，便于 8 行横向对齐
        row_h = BUTTON_ROW_H
        row_spacing = 3
        label_col_w = 30    # 这是 #x的宽度

        # 左上 串口列表（固定最大宽度；右侧竖向「刷新端口」）
        gb_port = QGroupBox("串口列表")
        self.gb_port = gb_port
        gb_port.setMaximumWidth(398)
        gb_port.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        port_outer = QHBoxLayout(gb_port)
        port_outer.setSpacing(8)
        port_outer.setContentsMargins(8, 8, 8, 8)

        left_col = QVBoxLayout()
        left_col.setSpacing(row_spacing)
        left_col.setContentsMargins(0, 0, 0, 0)

        self.port_checks: list[QCheckBox] = []
        self.port_edits: list[QLineEdit] = []
        self.port_status_labels: list[QLabel] = []

        for i in range(8):
            row = QHBoxLayout()
            row.setSpacing(10)
            cb = QCheckBox()
            cb.setChecked(True)
            cb.setFixedWidth(22)
            cb.toggled.connect(self.save_config)
            self.port_checks.append(cb)
            row.addWidget(cb)

            pl = QLabel(f"PORT{i + 1}")
            pl.setFixedWidth(PORT_LABEL_W)
            pl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(pl)

            ed = QLineEdit()
            ed.setReadOnly(True)
            ed.setFixedHeight(row_h)
            ed.setFixedWidth(80)
            self.port_edits.append(ed)
            row.addWidget(ed)

            st = QLabel("—")
            st.setMinimumWidth(72)
            st.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            st.setStyleSheet(f"color: {COLORS['muted']};")
            self.port_status_labels.append(st)
            row.addWidget(st)
            row.addStretch()
            left_col.addLayout(row)

        port_outer.addLayout(left_col, stretch=1)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(0)
        btn_col.addStretch(1)
        btn_refresh = QPushButton("刷\n新\n端\n口")
        btn_refresh.setObjectName("refreshPortBtn")
        btn_refresh.setFixedWidth(48)
        btn_refresh.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        btn_refresh.setMinimumHeight(row_h * 8)
        btn_refresh.clicked.connect(self.refresh_ports)
        btn_col.addWidget(btn_refresh, alignment=Qt.AlignmentFlag.AlignHCenter)
        btn_col.addStretch(1)
        port_outer.addLayout(btn_col)

        top.addWidget(gb_port, stretch=0)

        # 右上 固件设置
        gb_fw = QGroupBox("固件设置")
        vf = QVBoxLayout(gb_fw)
        vf.setSpacing(row_spacing)
        vf.setContentsMargins(8, 8, 8, 8)

        self.fw_checks: list[QCheckBox] = []
        self.fw_paths: list[QLineEdit] = []
        self.fw_addrs: list[QLineEdit] = []

        for i in range(8):
            row = QHBoxLayout()
            row.setSpacing(10)
            fc = QCheckBox()
            fc.setFixedWidth(22)
            fc.toggled.connect(self.save_config)
            self.fw_checks.append(fc)
            row.addWidget(fc)

            lab = QLabel(f"#{i + 1}")
            lab.setFixedWidth(label_col_w)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setStyleSheet(f"color: {COLORS['primary']}; font-weight: bold;")
            row.addWidget(lab)

            pe = QLineEdit()
            pe.setFixedHeight(row_h)
            pe.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            pe.textChanged.connect(self.save_config)
            self.fw_paths.append(pe)
            row.addWidget(pe, stretch=1)

            ae = QLineEdit()
            ae.setFixedHeight(row_h)
            ae.setMaximumWidth(120)
            ae.setText("0x0")
            ae.textChanged.connect(self.save_config)
            self.fw_addrs.append(ae)
            row.addWidget(ae)

            browse = QPushButton("浏览")
            browse.setFixedHeight(row_h)
            browse.setMinimumWidth(72)
            browse.clicked.connect(lambda checked=False, idx=i: self.browse_firmware(idx))
            row.addWidget(browse)

            vf.addLayout(row)

        top.addWidget(gb_fw, stretch=1)

        # 烧录统计（左）与 烧录设置（右）同一行
        stats_settings_wrap = QWidget()
        stats_settings_row = QHBoxLayout(stats_settings_wrap)
        stats_settings_row.setSpacing(12)
        stats_settings_row.setContentsMargins(0, 0, 0, 0)

        gb_stats = QGroupBox("烧录统计")
        ls = QHBoxLayout(gb_stats)
        ls.setContentsMargins(8, 1, 8, 1)
        ls.addWidget(QLabel("成功:"))
        self.lbl_ok = QLabel("0")
        self.lbl_ok.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
        ls.addWidget(self.lbl_ok)
        ls.addSpacing(16)
        ls.addWidget(QLabel("失败:"))
        self.lbl_fail = QLabel("0")
        self.lbl_fail.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold;")
        ls.addWidget(self.lbl_fail)
        ls.addSpacing(16)
        ls.addWidget(QLabel("总计:"))
        self.lbl_total = QLabel("0")
        self.lbl_total.setStyleSheet(f"color: {COLORS['primary']}; font-weight: bold;")
        ls.addWidget(self.lbl_total)
        ls.addStretch()
        btn_exp = QPushButton("导出")
        btn_exp.setMinimumWidth(72)
        btn_exp.clicked.connect(self.export_records)
        btn_clr = QPushButton("清空")
        btn_clr.setMinimumWidth(72)
        btn_clr.clicked.connect(self.clear_records)
        ls.addWidget(btn_exp)
        ls.addWidget(btn_clr)

        gb_set = QGroupBox("烧录设置")
        lset = QHBoxLayout(gb_set)
        lset.setContentsMargins(8, 1, 8, 1)
        lset.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        baud_items = ["115200", "230400", "460800", "921600", "1152000", "1500000", "2000000"]
        self.baud_combo.addItems(baud_items)
        self.baud_combo.setCurrentText("921600")
        self.baud_combo.currentTextChanged.connect(self.save_config)
        # 之前按 sizeHint()（以当前文本为准）收缩会导致切到更长选项时被截断。
        # 这里按最长项文本宽度计算，并在此基础上尽量保持“缩小约 1/4”。
        fm = QFontMetrics(self.baud_combo.font())
        max_text_w = max(fm.horizontalAdvance(s) for s in baud_items)

        # QSS 中：QComboBox padding: 6px 12px（左右各 12px），drop-down 宽度 22px
        # 额外加一点冗余，避免边缘裁切。
        min_w = int(max_text_w + 12 * 2 + 22 + 10)
        _bw = self.baud_combo.sizeHint().width()
        target_w = max(min_w, int(_bw * 0.75))
        self.baud_combo.setFixedWidth(target_w)
        lset.addWidget(self.baud_combo)
        lset.addSpacing(16)

        self.chk_erase = QCheckBox("擦除 Flash")
        self.chk_erase.toggled.connect(self.save_config)
        lset.addWidget(self.chk_erase)

        self.chk_auto = QCheckBox("自动烧录")
        self.chk_auto.toggled.connect(self.save_config)
        lset.addWidget(self.chk_auto)

        lset.addStretch()
        btn_flash = QPushButton("烧录")
        btn_flash.setMinimumWidth(72)
        btn_flash.clicked.connect(self.start_flash)
        lset.addWidget(btn_flash)

        stats_settings_row.addWidget(gb_stats, stretch=1)
        stats_settings_row.addWidget(gb_set, stretch=1)
        root.addWidget(stats_settings_wrap)

        # 运行日志（只读列表）
        gb_log = QGroupBox("运行日志")
        hl = QHBoxLayout(gb_log)
        hl.setContentsMargins(2, 3, 2, 2)
        hl.setSpacing(1)

        btn_clear_log = QPushButton("清\n除\n日\n志")
        # 复用「刷新端口」竖排按钮的样式逻辑：不固定单行高度，允许用 setMinimumHeight 控制整体高度
        btn_clear_log.setObjectName("refreshPortBtn")
        btn_clear_log.setFixedWidth(48)
        btn_clear_log.setMinimumHeight(row_h * 5)
        btn_clear_log.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        btn_clear_log.clicked.connect(self.clear_main_log)

        self.main_log_text = QPlainTextEdit()
        self.main_log_text.setObjectName("mainLogList")
        self.main_log_text.setReadOnly(True)
        self.main_log_text.setUndoRedoEnabled(False)
        self.main_log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.main_log_text.setFont(QFont(FONT_LOG_FAMILY, FONT_LOG_PT))
        self.main_log_text.setMinimumHeight(200)

        # 左：日志文本框（可拖选复制）；右：竖排「清除日志」按钮
        hl.addWidget(self.main_log_text, stretch=1)
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(0)
        right_col.addWidget(btn_clear_log, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        right_col.addStretch(1)
        hl.addLayout(right_col)
        root.addWidget(gb_log, stretch=1)

        for b in self.findChildren(QPushButton):
            polish_pushbutton(b, row_h)

    def _position_log_dialog(self, dlg: PortLogDialog, port: str) -> None:
        """烧录日志子窗体：第一个右缘贴屏右、顶不低于主窗客户区顶；后续相对上一个子窗略向左、向下偏移。"""
        try:
            fg = dlg.frameGeometry()
            dlg_w = fg.width() if fg.width() > 0 else (dlg.width() or 760)
            dlg_h = fg.height() if fg.height() > 0 else (dlg.height() or 520)

            screen = QGuiApplication.screenAt(self.frameGeometry().center())
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                return

            avail = screen.availableGeometry()
            # 垂直基准：主窗客户区顶边（标题栏下沿）
            try:
                title_bottom_global = self.mapToGlobal(self.contentsRect().topLeft()).y()
            except Exception:
                title_bottom_global = self.frameGeometry().top()
            y_base = max(avail.top(), int(title_bottom_global))

            cascade_dx = 28  # 相对上一个子窗向左
            cascade_dy = 28  # 相对上一个子窗向下

            prev_port = (
                self._log_dialog_order[-2]
                if len(self._log_dialog_order) >= 2
                else None
            )
            prev_dlg = self.log_windows.get(prev_port) if prev_port else None

            if (
                prev_dlg is not None
                and prev_port != port
                and prev_dlg.isVisible()
            ):
                pg = prev_dlg.frameGeometry()
                target_x = pg.left() - cascade_dx
                target_y = pg.top() + cascade_dy
            else:
                # 第一个子窗：右缘贴可用区右缘；顶从 y_base 起（槽位略向下错开，减轻与主窗重叠感）
                target_x = avail.left() + avail.width() - dlg_w
                idx = self._slot_index_for_port(port)
                y_step = 28
                y_offset = max(0, idx) * y_step
                target_y = y_base + y_offset

            # 保证整窗落在当前屏幕可用区内
            min_x = avail.left()
            max_x = avail.left() + avail.width() - dlg_w
            min_y = y_base
            max_y = avail.top() + avail.height() - dlg_h
            target_x = max(min_x, min(int(target_x), max_x))
            target_y = max(min_y, min(int(target_y), max_y))

            # 如果 dlg 没有父窗口，则 move 使用全局坐标；
            # 如果有父窗口，则 move 使用父窗口坐标系，需要 mapFromGlobal 转换。
            if dlg.parentWidget() is None:
                dlg.move(int(target_x), int(target_y))
            else:
                local = self.mapFromGlobal(QPoint(int(target_x), int(target_y)))
                dlg.move(local)
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            # 失败就不影响主程序运行
            return

    def _delayed_init(self):
        self.load_config()
        self.refresh_ports()
        threading.Thread(target=self._monitor_ports, daemon=True).start()
        self._append_main_log("就绪。已启动串口监控。")

    def _append_main_log(self, message: str):
        ts = time.strftime("%H:%M:%S")
        self.main_log_text.moveCursor(QTextCursor.MoveOperation.End)
        self.main_log_text.insertPlainText(f"[{ts}] {message}\n")
        lines = self.main_log_text.toPlainText().splitlines()
        if len(lines) > self._max_main_log_lines:
            self.main_log_text.setPlainText(
                "\n".join(lines[-self._max_main_log_lines :]) + "\n"
            )
        sb = self.main_log_text.verticalScrollBar()
        sb.setValue(sb.maximum())
        cur = self.main_log_text.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.main_log_text.setTextCursor(cur)

    def clear_main_log(self):
        self.main_log_text.clear()

    @pyqtSlot(str, str)
    def _on_sub_log(self, port: str, line: str):
        dlg = self.log_windows.get(port)
        if dlg:
            dlg.append_line(line)

    @pyqtSlot(str)
    def _slot_create_log_dialog(self, port: str):
        def on_close():
            self.stop_flash(port)

        # 不传父窗口：避免 move 坐标系混淆（父坐标 vs 全局坐标），导致定位约束看似“无效”
        dlg = PortLogDialog(None, port, on_close=on_close)
        self.log_windows[port] = dlg
        try:
            while port in self._log_dialog_order:
                self._log_dialog_order.remove(port)
        except Exception:
            pass
        self._log_dialog_order.append(port)
        dlg.show()
        # show 后下一帧再定位：此时 frameGeometry 与主窗坐标均稳定；且 move 需配合 mapFromGlobal（见 _position_log_dialog）
        def _place_and_signal():
            self._position_log_dialog(dlg, port)
            self._signals.log_dialog_ready.emit(port)

        QTimer.singleShot(0, _place_and_signal)

    @pyqtSlot(int, str, str)
    def _slot_port_status(self, slot: int, kind: str, text: str):
        if slot < 0 or slot >= 8:
            return
        lbl = self.port_status_labels[slot]
        lbl.setText(text)
        if kind == "idle":
            lbl.setStyleSheet(f"color: {COLORS['muted']};")
        elif kind == "flash":
            lbl.setStyleSheet(f"color: {COLORS['info']}; font-weight: bold;")
        elif kind == "ok":
            lbl.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
        elif kind == "fail":
            lbl.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold;")

    @pyqtSlot()
    def _slot_stats(self):
        self.lbl_ok.setText(str(self.flash_success_count))
        self.lbl_fail.setText(str(self.flash_fail_count))
        self.lbl_total.setText(str(self.flash_total_count))

    def _set_slot_status(self, slot: int, kind: str, text: str):
        self._signals.port_status.emit(slot, kind, text)

    def _slot_index_for_port(self, port: str) -> int:
        for i in range(8):
            if self.port_edits[i].text().strip() == port:
                return i
        return -1

    def _set_port_status_by_name(self, port: str, kind: str, text: str):
        idx = self._slot_index_for_port(port)
        if idx >= 0:
            self._set_slot_status(idx, kind, text)

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        for i in range(8):
            name = ports[i] if i < len(ports) else ""
            old = self._last_port_slots[i]
            if old != name:
                self._set_slot_status(i, "idle", "—")
            self.port_edits[i].setText(name)
            self._last_port_slots[i] = name
        self.save_config()

    def _monitor_ports(self):
        old = set()
        while True:
            try:
                cur = {p.device for p in list_ports.comports()}
                if cur != old:
                    self._signals.ports_changed.emit(old.copy(), cur.copy())
                    old = cur
                time.sleep(1.5)
            except Exception:
                time.sleep(1.5)

    @pyqtSlot(object, object)
    def _handle_port_changes(self, old_ports: set, current_ports: set):
        for removed in old_ports - current_ports:
            if removed in self.log_windows:
                try:
                    self.log_windows[removed].close()
                except Exception:
                    pass
                self.log_windows.pop(removed, None)
                try:
                    if removed in self._log_dialog_order:
                        self._log_dialog_order.remove(removed)
                except Exception:
                    pass

        new_ports = current_ports - old_ports
        if new_ports:
            self._signals.main_log.emit(f"检测到新串口: {', '.join(sorted(new_ports))}")
            if self.chk_auto.isChecked():
                QTimer.singleShot(1000, lambda p=list(new_ports): self.handle_new_ports(p))

        self.refresh_ports()

    def handle_new_ports(self, new_ports: list):
        firmwares = []
        for i in range(8):
            if not self.fw_checks[i].isChecked():
                continue
            path = self.fw_paths[i].text().strip()
            addr = self.fw_addrs[i].text().strip()
            if path and os.path.exists(path):
                firmwares.append((path, addr))

        if not firmwares:
            self._signals.main_log.emit("自动烧录：未选择有效固件，已跳过。")
            return

        for port in new_ports:
            self._signals.main_log.emit(f"自动烧录启动: {port}")
            threading.Thread(target=self.flash_process_multi, args=(port, firmwares), daemon=True).start()

    def load_config(self):
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            else:
                cfg = {}
        except Exception:
            cfg = {}

        paths = cfg.get("firmware_paths", [""] * 8)
        addrs = cfg.get("firmware_addresses", ["0x0"] * 8)
        enables = cfg.get("firmware_enables", [False] * 8)
        port_en = cfg.get("port_enables", [True] * 8)

        for i in range(8):
            if i < len(paths) and paths[i] and os.path.exists(paths[i]):
                self.fw_paths[i].setText(paths[i])
            if i < len(addrs):
                self.fw_addrs[i].setText(addrs[i] or "0x0")
            if i < len(enables):
                self.fw_checks[i].setChecked(enables[i])
            if i < len(port_en):
                self.port_checks[i].setChecked(port_en[i])

        if "baudrate" in cfg:
            self.baud_combo.setCurrentText(str(cfg["baudrate"]))
        if "erase_flash" in cfg:
            self.chk_erase.setChecked(cfg["erase_flash"])
        if "auto_flash" in cfg:
            self.chk_auto.setChecked(cfg["auto_flash"])

    def save_config(self):
        try:
            data = {
                "firmware_paths": [self.fw_paths[i].text() for i in range(8)],
                "firmware_addresses": [self.fw_addrs[i].text() for i in range(8)],
                "firmware_enables": [self.fw_checks[i].isChecked() for i in range(8)],
                "port_enables": [self.port_checks[i].isChecked() for i in range(8)],
                "baudrate": int(self.baud_combo.currentText()),
                "erase_flash": self.chk_erase.isChecked(),
                "auto_flash": self.chk_auto.isChecked(),
            }
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._signals.main_log.emit(f"保存配置失败: {e}")

    def browse_firmware(self, index: int):
        initial = os.path.dirname(self.fw_paths[index].text()) or os.getcwd()
        fn, _ = QFileDialog.getOpenFileName(
            self,
            "选择固件",
            initial,
            "二进制 (*.bin);;所有文件 (*.*)",
        )
        if fn:
            self.fw_paths[index].setText(fn)
            self.save_config()

    def start_flash(self):
        selected = []
        for i in range(8):
            name = self.port_edits[i].text().strip()
            if name and self.port_checks[i].isChecked():
                selected.append(name)

        if not selected:
            self._signals.main_log.emit("错误: 请至少启用并选择一个已连接的串口。")
            return

        firmwares = []
        for i in range(8):
            if not self.fw_checks[i].isChecked():
                continue
            path = self.fw_paths[i].text().strip()
            addr = self.fw_addrs[i].text().strip()
            if path and os.path.exists(path):
                firmwares.append((path, addr))

        if not firmwares:
            self._signals.main_log.emit("错误: 请至少启用一个有效固件。")
            return

        for port in selected:
            threading.Thread(target=self.flash_process_multi, args=(port, firmwares), daemon=True).start()

    def _wait_log_dialog(self, port: str):
        self._log_dialog_events[port] = threading.Event()
        self._signals.create_log_dialog.emit(port)
        self._log_dialog_events[port].wait(timeout=10.0)

    def _sub_log(self, port: str, line: str):
        """工作线程调用：子窗口日志必须在主线程追加。"""
        self._signals.sub_log.emit(port, line)

    def _run_esptool(self, args, port, cancel_event):
        lines: list[str] = []
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, _ESPTOOL_SUBPROC_FLAG] + list(args)
        else:
            cmd = [sys.executable, "-m", "esptool"] + list(args)
        creationflags = 0
        if os.name == "nt":
            try:
                creationflags = subprocess.CREATE_NO_WINDOW
            except Exception:
                creationflags = 0

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        if port:
            self.flash_processes[port] = proc

        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("cancelled")
                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.01)
                    continue
                text_line = line.rstrip("\r\n")
                lines.append(text_line)
                if port:
                    self._signals.sub_log.emit(port, text_line)
            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(_format_esptool_exit_error(rc, lines))
        finally:
            if port:
                try:
                    if self.flash_processes.get(port) is proc:
                        del self.flash_processes[port]
                except Exception:
                    pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

        return "\n".join(lines)

    def _release_port(self, port: str):
        try:
            s = serial.Serial(port=port, baudrate=115200, timeout=0)
            try:
                s.dtr = False
                s.rts = False
            except Exception:
                pass
            s.close()
        except Exception:
            pass

    def flash_process_multi(self, port: str, firmwares: list):
        cancel_event = threading.Event()
        self.flash_cancel_events[port] = cancel_event

        self._wait_log_dialog(port)
        if port not in self.log_windows:
            self._signals.main_log.emit(f"无法打开日志窗口: {port}")
            return

        self._set_port_status_by_name(port, "flash", "烧录中")
        self._signals.main_log.emit(f"开始烧录: {port}")

        chip_type = None
        mac_address = "Unknown"

        try:
            if cancel_event.is_set():
                raise RuntimeError("cancelled")

            self._sub_log(port, "检测芯片类型...")
            output = self._run_esptool(["--port", port, "read-mac"], port, cancel_event)

            out_u = output.upper()
            if "ESP8266" in out_u:
                chip_type = "ESP8266"
            elif "ESP32-S3" in out_u or "ESP32S3" in out_u:
                chip_type = "ESP32-S3"
            elif "ESP32-S2" in out_u or "ESP32S2" in out_u:
                chip_type = "ESP32-S2"
            elif "ESP32-C3" in out_u or "ESP32C3" in out_u:
                chip_type = "ESP32-C3"
            elif "ESP32-C6" in out_u or "ESP32C6" in out_u:
                chip_type = "ESP32-C6"
            elif "ESP32-H2" in out_u or "ESP32H2" in out_u:
                chip_type = "ESP32-H2"
            elif "ESP32-P4" in out_u or "ESP32P4" in out_u:
                chip_type = "ESP32-P4"
            elif "ESP32-C2" in out_u or "ESP32C2" in out_u:
                chip_type = "ESP32-C2"
            elif "ESP32-C61" in out_u or "ESP32C61" in out_u:
                chip_type = "ESP32-C61"
            elif "ESP32-C5" in out_u or "ESP32C5" in out_u:
                chip_type = "ESP32-C5"
            elif "ESP32-E22" in out_u or "ESP32E22" in out_u:
                chip_type = "ESP32-E22"
            elif "ESP32-H21" in out_u or "ESP32H21" in out_u:
                chip_type = "ESP32-H21"
            elif "ESP32-H4" in out_u or "ESP32H4" in out_u:
                chip_type = "ESP32-H4"
            elif "ESP32-S31" in out_u or "ESP32S31" in out_u:
                chip_type = "ESP32-S31"
            elif "ESP32" in out_u:
                chip_type = "ESP32"


            if not chip_type:
                self._sub_log(port, "警告: 未能自动识别芯片类型，将使用通用参数")
                chip_type = "ESP32"

            self._sub_log(port, f"检测到芯片类型: {chip_type}")

            m = re.search(
                r"MAC:\s*([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})",
                output,
            )
            if m:
                mac_address = m.group(1)
                self._sub_log(port, f"MAC地址: {mac_address}")

            chip_param = self.get_chip_param(chip_type)
            if not chip_param:
                self._sub_log(port, f"不支持的芯片类型: {chip_type}")
                self.add_flash_record(port, chip_type, mac_address, False, "不支持的芯片类型")
                self._set_port_status_by_name(port, "fail", "失败")
                return

            if self.chk_erase.isChecked():
                self._sub_log(port, "正在擦除Flash...")
                self._run_esptool(
                    ["--port", port, "--baud", self.baud_combo.currentText(), "erase_flash"],
                    port,
                    cancel_event,
                )
                self._sub_log(port, "Flash擦除完成!")

            for firmware, address in firmwares:
                if cancel_event.is_set():
                    raise RuntimeError("cancelled")
                flash_args = [
                    "--port",
                    port,
                    "--baud",
                    self.baud_combo.currentText(),
                    "--before",
                    "default_reset",
                    "--after",
                    "hard_reset",
                    "write-flash",
                    address,
                    firmware,
                ]
                self._sub_log(port, f"执行命令: esptool {' '.join(flash_args)}")
                self._run_esptool(flash_args, port, cancel_event)
                self._sub_log(port, f"端口 {port} 固件 {firmware} 烧录完成!")

            self._sub_log(port, f"端口 {port} 所有固件烧录完成!")
            self.add_flash_record(port, chip_type, mac_address, True, "")
            self._set_port_status_by_name(port, "ok", "完成")
            self._signals.main_log.emit(f"烧录完成: {port}")

        except Exception as e:
            error_msg = str(e)
            if "cancelled" in error_msg.lower() or error_msg == "cancelled":
                self._sub_log(port, f"端口 {port} 已停止烧录")
                self._signals.main_log.emit(f"已停止: {port}")
                self._set_port_status_by_name(port, "idle", "已停止")
                self._release_port(port)
            else:
                self._sub_log(port, f"端口 {port} 烧录错误: {error_msg}")
                self._signals.main_log.emit(f"烧录失败: {port} — {error_msg}")
                self.add_flash_record(port, chip_type if chip_type else "Unknown", mac_address, False, error_msg)
                self._set_port_status_by_name(port, "fail", "失败")
        finally:
            try:
                del self.flash_cancel_events[port]
            except Exception:
                pass
            try:
                del self.flash_processes[port]
            except Exception:
                pass
            try:
                del self._log_dialog_events[port]
            except Exception:
                pass

    def close_log_window(self, port: str):
        w = self.log_windows.pop(port, None)
        try:
            if port in self._log_dialog_order:
                self._log_dialog_order.remove(port)
        except Exception:
            pass
        if w:
            try:
                w.close()
            except Exception:
                pass

    def stop_flash(self, port=None):
        if port is None:
            for p in list(self.flash_cancel_events.keys()):
                try:
                    self.flash_cancel_events[p].set()
                except Exception:
                    pass
                try:
                    proc = self.flash_processes.get(p)
                    if proc and proc.poll() is None:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                        else:
                            proc.terminate()
                except Exception:
                    pass
                try:
                    self._release_port(p)
                except Exception:
                    pass
            return

        try:
            if port in self.flash_cancel_events:
                self.flash_cancel_events[port].set()
        except Exception:
            pass

        try:
            proc = self.flash_processes.get(port)
            if proc and proc.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    proc.terminate()
        except Exception:
            pass
        try:
            self._release_port(port)
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            self.stop_flash(None)
        except Exception:
            pass
        for p in list(self.log_windows.keys()):
            try:
                self.log_windows[p].close()
            except Exception:
                pass
        self._log_dialog_order.clear()
        try:
            self.save_config()
        except Exception:
            pass
        event.accept()

    def get_chip_param(self, chip_type: str):
        chip_map = {
            "ESP32": "esp32",
            "ESP32-S2": "esp32s2",
            "ESP32-S3": "esp32s3",
            "ESP32-C2": "esp32c2",
            "ESP32-C3": "esp32c3",
            "ESP32-C6": "esp32c6",
            "ESP32-H2": "esp32h2",
            "ESP32-P4": "esp32p4",
        }
        return chip_map.get(chip_type, "esp32")

    def add_flash_record(self, port, chip_type, mac_address, success, error_msg=""):
        self.flash_records.append(
            {
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "port": port,
                "chip_type": chip_type,
                "mac_address": mac_address,
                "success": success,
                "error_msg": error_msg or "",
            }
        )
        self.flash_total_count += 1
        if success:
            self.flash_success_count += 1
        else:
            self.flash_fail_count += 1
        self._signals.stats_update.emit()

    def export_records(self):
        if not self.flash_records:
            QMessageBox.information(self, "提示", "暂无烧录记录")
            return
        default_name = f"烧录记录_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        fn, _ = QFileDialog.getSaveFileName(
            self,
            "导出记录",
            default_name,
            "CSV (*.csv);;所有文件 (*.*)",
        )
        if not fn:
            return
        try:
            with open(fn, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["烧录时间", "端口", "芯片型号", "MAC地址", "状态", "错误信息"])
                for r in self.flash_records:
                    w.writerow(
                        [
                            r["time"],
                            r["port"],
                            r["chip_type"],
                            r["mac_address"],
                            "成功" if r["success"] else "失败",
                            r.get("error_msg", ""),
                        ]
                    )
            self._signals.main_log.emit(f"记录已导出: {fn}")
            QMessageBox.information(self, "成功", f"已导出 {len(self.flash_records)} 条记录。")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def clear_records(self):
        if not self.flash_records:
            QMessageBox.information(self, "提示", "暂无烧录记录")
            return
        if QMessageBox.question(
            self,
            "确认",
            f"确定清空 {len(self.flash_records)} 条记录？",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.flash_records.clear()
        self.flash_success_count = 0
        self.flash_fail_count = 0
        self.flash_total_count = 0
        self._slot_stats()
        self._signals.main_log.emit("已清空烧录记录。")


def main():
    if not _check_deps():
        sys.exit(1)

    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    _ic = _resolve_app_icon()
    if not _ic.isNull():
        app.setWindowIcon(_ic)
    # Windows 默认 windowsvista 样式常导致 QSS 在主窗口上渲染不完整；Fusion 与子窗体一致
    _fusion = QStyleFactory.create("Fusion")
    if _fusion is not None:
        app.setStyle(_fusion)
    app.setFont(QFont(FONT_FAMILY, FONT_PT))
    app.setStyleSheet(app_stylesheet())

    w = MainWindow()
    w.show()
    # Windows 上部分环境下需在首帧后再设一次，标题栏/任务栏才稳定显示
    if not _ic.isNull():

        def _reapply_icons() -> None:
            app.setWindowIcon(_ic)
            w.setWindowIcon(_ic)

        QTimer.singleShot(0, _reapply_icons)

    sys.exit(app.exec())


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == _ESPTOOL_SUBPROC_FLAG:
        _run_esptool_cli_only()
    else:
        main()
