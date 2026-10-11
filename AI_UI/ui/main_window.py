from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QFrame,
    QApplication,
    QSizePolicy,
    QSpacerItem,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from ui.pages.ai_page import AIPage
from ui.pages.status_page import StatusPage
from ui.pages.contacts_page import DataPage
from ui.pages.quick_messages_page import QuickMessagesPage
from core.state_manager import state_manager

# ─────────────────────────────────────────────────────────────
# GLOBAL STYLESHEET
# ─────────────────────────────────────────────────────────────

APP_STYLE = """
/* ===== GLOBAL ===== */
QWidget {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 16px;
    color: #2c3e50;
    background-color: #f0f4f8;
}
QMainWindow { background-color: #f0f4f8; }

/* ===== SIDEBAR ===== */
#sidebar {
    background-color: #1e2d3d;
    border: none;
}
#sidebarLogo {
    color: #ecf0f1;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 10px 20px 6px 20px;
    background: transparent;
}
#sidebarDivider {
    background-color: #2d3f53;
    max-height: 1px;
    border: none;
}
#navBtn {
    background-color: transparent;
    color: #8fa8c0;
    border: none;
    border-left: 3px solid transparent;
    text-align: left;
    padding: 13px 20px;
    font-size: 16px;
    font-weight: 600;
    border-radius: 0px;
    min-height: 44px;
}
#navBtn:hover {
    background-color: #253648;
    color: #ecf0f1;
}
#navBtn[active="true"] {
    background-color: #253648;
    color: #ffffff;
    border-left: 3px solid #3498db;
}
#sidebarVersion {
    color: #4a6278;
    font-size: 14px;
    padding: 8px 20px;
    background: transparent;
}

/* ===== HEADER ===== */
#headerBar {
    background-color: #1e2d3d;
    border-bottom: 2px solid #3498db;
    min-height: 52px;
    max-height: 52px;
}
#headerTitle {
    color: #ffffff;
    font-size: 21px;
    font-weight: 700;
    letter-spacing: 0.5px;
    background: transparent;
    padding: 0 24px;
}
#headerSub {
    color: #7fa8c8;
    font-size: 14px;
    background: transparent;
    padding: 0 24px;
}

/* ===== PRIMARY BUTTON ===== */
QPushButton {
    background-color: #3498db;
    color: white;
    border: none;
    border-radius: 5px;
    padding: 8px 20px;
    font-weight: 600;
    min-height: 32px;
}
QPushButton:hover  { background-color: #2980b9; }
QPushButton:pressed { background-color: #1f6fa8; }
QPushButton:disabled { background-color: #c8d6e5; color: #7f8c8d; }

/* ===== DANGER / SUCCESS / SECONDARY ===== */
QPushButton[class="danger"]          { background-color: #e74c3c; }
QPushButton[class="danger"]:hover    { background-color: #c0392b; }
QPushButton[class="success"]         { background-color: #27ae60; }
QPushButton[class="success"]:hover   { background-color: #1e8449; }
QPushButton[class="secondary"]       { background-color: #7f8c8d; }
QPushButton[class="secondary"]:hover { background-color: #626d6e; }

/* ===== TAB BUTTONS ===== */
QPushButton[class="tab"] {
    background-color: transparent;
    color: #7f8c8d;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    padding: 10px 22px;
    font-size: 16px;
    font-weight: 600;
    min-height: 38px;
}
QPushButton[class="tab"]:hover {
    color: #2c3e50;
    border-bottom: 2px solid #bdc3c7;
}
QPushButton[class="tab"][active="true"] {
    color: #3498db;
    border-bottom: 2px solid #3498db;
    background-color: transparent;
}

/* ===== CARD ===== */
#card {
    background-color: white;
    border: 1px solid #dce3ea;
    border-radius: 8px;
}
#cardHeader {
    background-color: #f8fafc;
    border-bottom: 1px solid #e8edf2;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 16px;
}
#cardTitle {
    font-size: 15px;
    font-weight: 700;
    color: #7f8c8d;
    letter-spacing: 1px;
    background: transparent;
}

/* ===== PAGE TITLE ===== */
#pageTitle {
    font-size: 21px;
    font-weight: 700;
    color: #2c3e50;
    background: transparent;
    padding: 4px 0;
}
#pageSub {
    font-size: 15px;
    color: #95a5a6;
    background: transparent;
}

/* ===== INPUTS ===== */
QLineEdit, QComboBox {
    background-color: white;
    border: 1.5px solid #d5dde5;
    border-radius: 5px;
    padding: 8px 12px;
    font-size: 16px;
    min-height: 34px;
    color: #2c3e50;
}
QLineEdit:focus, QComboBox:focus {
    border: 1.5px solid #3498db;
}
QLineEdit::placeholder { color: #bdc3c7; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: white;
    border: 1px solid #d5dde5;
    selection-background-color: #d6eaf8;
    selection-color: #2c3e50;
}

/* ===== TEXT EDIT ===== */
QTextEdit {
    background-color: white;
    border: 1px solid #dce3ea;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 16px;
    color: #2c3e50;
}

/* ===== TABLE ===== */
QTableWidget {
    background-color: white;
    border: 1px solid #dce3ea;
    border-radius: 6px;
    gridline-color: #f0f4f8;
    font-size: 16px;
    outline: none;
    alternate-background-color: #f8fafc;
}
QTableWidget::item {
    padding: 6px 10px;
    border: none;
}
QTableWidget::item:selected {
    background-color: #d6eaf8;
    color: #2c3e50;
}
QHeaderView::section {
    background-color: #2c3e50;
    color: white;
    padding: 9px 10px;
    border: none;
    font-weight: 700;
    font-size: 15px;
    letter-spacing: 0.3px;
}
QTableWidget QTableCornerButton::section {
    background-color: #2c3e50;
}

/* ===== GROUPBOX ===== */
QGroupBox {
    border: 1.5px solid #d5dde5;
    border-radius: 6px;
    margin-top: 18px;
    padding: 14px 8px 8px 8px;
    font-weight: 700;
    color: #2c3e50;
    background: white;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    top: -9px;
    background-color: white;
    padding: 0 6px;
    color: #3498db;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

/* ===== CHECKBOX ===== */
QCheckBox {
    color: #2c3e50;
    spacing: 8px;
    font-size: 16px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #bdc3c7;
    border-radius: 3px;
    background: white;
}
QCheckBox::indicator:checked {
    background-color: #3498db;
    border-color: #3498db;
}
QCheckBox::indicator:hover { border-color: #3498db; }

/* ===== FORM LABEL ===== */
#formLabel {
    font-size: 15px;
    font-weight: 600;
    color: #7f8c8d;
    letter-spacing: 0.3px;
    background: transparent;
}

/* ===== STATUS DOTS ===== */
#dotOk    { color: #27ae60; font-size: 19px; background: transparent; }
#dotError { color: #e74c3c; font-size: 19px; background: transparent; }
#dotWarn  { color: #f39c12; font-size: 19px; background: transparent; }
#dotNa    { color: #bdc3c7; font-size: 19px; background: transparent; }

/* ===== STATUS TEXT ===== */
#statusOk    { color: #27ae60; font-weight: 700; background: transparent; }
#statusError { color: #e74c3c; font-weight: 700; background: transparent; }
#statusWarn  { color: #f39c12; font-weight: 700; background: transparent; }
#statusNa    { color: #95a5a6; font-weight: 400; background: transparent; }

/* ===== PANEL HEADER ===== */
#panelHeader {
    background-color: #f8fafc;
    border-bottom: 1px solid #e8edf2;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
#panelTitle {
    font-size: 15px;
    font-weight: 700;
    color: #5d7a9a;
    letter-spacing: 0.8px;
    background: transparent;
    padding: 8px 14px;
}

/* ===== SCROLLBAR ===== */
QScrollBar:vertical {
    background: #f0f4f8;
    width: 7px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #c8d6e5;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #a8bcd4; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #f0f4f8;
    height: 7px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #c8d6e5;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ===== DIALOG ===== */
QDialog {
    background-color: white;
}
QDialog QLabel { background: transparent; }
"""


class MainWindow(QMainWindow):

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo cửa sổ chính — áp dụng stylesheet toàn cục
         *            và xây dựng giao diện.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi QMainWindow.__init__().
         *   2. Áp dụng APP_STYLE cho toàn bộ ứng dụng.
         *   3. Gọi setup_ui() để tạo layout và các trang.
         */
        """
        super().__init__()

        QApplication.instance().setStyleSheet(APP_STYLE)
        self.setup_ui()

    # =====================================
    # UI
    # =====================================

    def setup_ui(self):
        """
        /**
         * Chức năng: Xây dựng toàn bộ cấu trúc giao diện gồm header bar,
         *            sidebar điều hướng và 4 trang nội dung trong QStackedWidget.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đặt tiêu đề cửa sổ, kích thước và kích thước tối thiểu.
         *   2. Tạo header bar với tên hệ thống.
         *   3. Tạo sidebar với 4 nút điều hướng và nhãn phiên bản.
         *   4. Tạo QStackedWidget chứa AIPage, StatusPage, DataPage, QuickMessagesPage.
         *   5. Kết nối sự kiện click nút với _set_active_nav().
         *   6. Kích hoạt trang AIPage mặc định.
         */
        """
        self.setWindowTitle("HỆ THỐNG KHẨN CẤP AI")
        self.resize(1440, 860)
        self.setMinimumSize(1100, 700)

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ─────────────────────────────────
        # HEADER BAR
        # ─────────────────────────────────
        header_bar = QFrame()
        header_bar.setObjectName("headerBar")
        header_bar.setFixedHeight(52)
        header_bar.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )
        h_layout = QHBoxLayout(header_bar)
        h_layout.setContentsMargins(0, 0, 24, 0)
        h_layout.setSpacing(0)

        title_lbl = QLabel(
            "HỆ THỐNG TRUYỀN TIN VÀ LIÊN LẠC KHẨN CẤP ỨNG DỤNG AI"
        )
        title_lbl.setObjectName("headerTitle")
        title_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        h_layout.addWidget(title_lbl, 1)
        root_layout.addWidget(header_bar)

        # ─────────────────────────────────
        # BODY  (sidebar + content)
        # ─────────────────────────────────
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # ─────────────────────────────────
        # SIDEBAR
        # ─────────────────────────────────
        self._sidebar = QWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(190)
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        logo_lbl = QLabel("ĐIỀU HƯỚNG")
        logo_lbl.setObjectName("sidebarLogo")

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        divider.setFixedHeight(1)

        self.ai_btn      = self._make_nav_btn("  Nhận Diện")
        self.status_btn  = self._make_nav_btn("  Trạng Thái")
        self.data_btn    = self._make_nav_btn("  Dữ Liệu")
        self.quick_btn   = self._make_nav_btn("  Tin Nhắn Nhanh")

        self.ai_btn.clicked.connect(lambda: self._set_active_nav(0))
        self.status_btn.clicked.connect(lambda: self._set_active_nav(1))
        self.data_btn.clicked.connect(lambda: self._set_active_nav(2))
        self.quick_btn.clicked.connect(lambda: self._set_active_nav(3))

        sidebar_layout.addSpacing(12)
        sidebar_layout.addWidget(logo_lbl)
        sidebar_layout.addWidget(divider)
        sidebar_layout.addSpacing(6)
        sidebar_layout.addWidget(self.ai_btn)
        sidebar_layout.addWidget(self.status_btn)
        sidebar_layout.addWidget(self.data_btn)
        sidebar_layout.addWidget(self.quick_btn)
        sidebar_layout.addStretch()

        ver_lbl = QLabel("v1.0  —  ESP32 + AI")
        ver_lbl.setObjectName("sidebarVersion")
        sidebar_layout.addWidget(ver_lbl)
        sidebar_layout.addSpacing(12)

        # ─────────────────────────────────
        # PAGES
        # ─────────────────────────────────
        self.pages = QStackedWidget()

        self.ai_page      = AIPage()
        self.status_page  = StatusPage()
        self.data_page    = DataPage()
        self.quick_page   = QuickMessagesPage()

        self.pages.addWidget(self.ai_page)
        self.pages.addWidget(self.status_page)
        self.pages.addWidget(self.data_page)
        self.pages.addWidget(self.quick_page)

        body_layout.addWidget(self._sidebar)
        body_layout.addWidget(self.pages, 1)

        root_layout.addLayout(body_layout, 1)

        # Active default
        self._nav_btns = [self.ai_btn, self.status_btn, self.data_btn, self.quick_btn]
        self._set_active_nav(0)

    # ─────────────────────────────────
    # HELPERS
    # ─────────────────────────────────

    def _make_nav_btn(self, text: str) -> QPushButton:
        """
        /**
         * Chức năng: Tạo một nút điều hướng sidebar với objectName và
         *            thuộc tính active mặc định False.
         * Tham số:
         *   - text : nhãn hiển thị trên nút
         * Trả về: QPushButton đã cấu hình sẵn
         * Luồng hoạt động:
         *   1. Tạo QPushButton với text.
         *   2. Gán objectName "navBtn" để stylesheet nhận dạng.
         *   3. Đặt property active = False và cursor tay.
         */
        """
        btn = QPushButton(text)
        btn.setObjectName("navBtn")
        btn.setProperty("active", False)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _set_active_nav(self, index: int):
        """
        /**
         * Chức năng: Cập nhật trạng thái active của nút điều hướng và
         *            chuyển trang nội dung tương ứng.
         * Tham số:
         *   - index : chỉ số trang cần kích hoạt (0=AI, 1=Status, 2=Data, 3=Quick)
         * Trả về: None
         * Luồng hoạt động:
         *   1. Duyệt qua tất cả nút: đặt property active đúng/sai theo index.
         *   2. Unpolish/polish từng nút để Qt áp lại stylesheet.
         *   3. Chuyển QStackedWidget sang trang index.
         */
        """
        for i, btn in enumerate(self._nav_btns):
            is_active = (i == index)
            btn.setProperty("active", is_active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.pages.setCurrentIndex(index)
