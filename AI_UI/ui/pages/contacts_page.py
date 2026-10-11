import html as _html
import re

from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QTextEdit,
    QHeaderView,
    QMessageBox,
    QDialog,
    QComboBox,
    QGroupBox,
    QCheckBox,
    QAbstractItemView,
    QFrame,
)
from PyQt5.QtCore import Qt

from core.event_bus import bus
from services.database_service import database_service
from services.uart_service import uart_service


# ─────────────────────────────────────────
# ROLE SELECTOR WIDGET
# ─────────────────────────────────────────

class RoleSelector(QGroupBox):

    _ROLES = ["ƯU TIÊN", "CHĂM SÓC", "CẦN THIẾT", "NHẬN TIN NHẮN"]

    def __init__(self, parent=None):
        """
        /**
         * Chức năng: Khởi tạo widget chọn vai trò liên hệ — tạo QCheckBox cho 4 vai trò.
         * Tham số:
         *   parent : widget cha (mặc định None)
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo QVBoxLayout chứa 4 QCheckBox tương ứng 4 vai trò.
         *   2. Lưu mapping role → checkbox vào self._boxes.
         */
        """
        super().__init__("Vai trò", parent)
        layout = QVBoxLayout()
        layout.setSpacing(6)
        self._boxes = {}
        for role in self._ROLES:
            cb = QCheckBox(role)
            layout.addWidget(cb)
            self._boxes[role] = cb
        self.setLayout(layout)

    def get_selected(self) -> list:
        """
        /**
         * Chức năng: Lấy danh sách vai trò đang được chọn; mặc định ["CHĂM SÓC"] nếu trống.
         * Tham số: Không
         * Trả về: list[str] — tên các vai trò đang checked
         */
        """
        selected = [r for r, cb in self._boxes.items() if cb.isChecked()]
        return selected if selected else ["CHĂM SÓC"]

    def set_selected(self, roles: list):
        """
        /**
         * Chức năng: Đánh dấu checked cho các checkbox thuộc danh sách roles.
         * Tham số:
         *   roles : list[str] tên vai trò cần tick
         * Trả về: None
         */
        """
        for role, cb in self._boxes.items():
            cb.setChecked(role in roles)

    def clear(self):
        """
        /**
         * Chức năng: Bỏ tick tất cả checkbox vai trò.
         * Tham số: Không
         * Trả về: None
         */
        """
        for cb in self._boxes.values():
            cb.setChecked(False)


# ─────────────────────────────────────────
# EDIT CONTACT DIALOG
# ─────────────────────────────────────────

class EditContactDialog(QDialog):

    def __init__(self, contact_id, name, phone, relation, roles, parent=None):
        """
        /**
         * Chức năng: Tạo dialog chỉnh sửa liên hệ với các trường ID, tên, SĐT,
         *            quan hệ, vai trò và hai nút Lưu/Hủy.
         * Tham số:
         *   contact_id : ID hiện tại của liên hệ
         *   name       : tên hiện tại
         *   phone      : số điện thoại hiện tại
         *   relation   : quan hệ hiện tại
         *   roles      : list[str] vai trò hiện tại
         *   parent     : widget cha
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo các QLineEdit, QComboBox và RoleSelector được điền sẵn dữ liệu cũ.
         *   2. Thêm nút "Lưu thay đổi" (accept) và "Hủy" (reject).
         */
        """
        super().__init__(parent)
        self.setWindowTitle("Sửa Liên Hệ")
        self.setMinimumWidth(400)
        self.setStyleSheet("QDialog { background: white; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        def _field(label_text, widget):
            lbl = QLabel(label_text)
            lbl.setObjectName("formLabel")
            box = QVBoxLayout()
            box.setSpacing(4)
            box.addWidget(lbl)
            box.addWidget(widget)
            return box

        self.id_input    = QLineEdit(contact_id)
        self.name_input  = QLineEdit(name)
        self.phone_input = QLineEdit(phone)

        self.relation_combo = QComboBox()
        self.relation_combo.addItems([
            "Con trai", "Con gái", "Vợ", "Chồng",
            "Anh trai", "Chị gái", "Em trai", "Em gái",
            "Người chăm sóc", "Hàng xóm", "Bạn bè", "Khác",
        ])
        idx = self.relation_combo.findText(relation)
        if idx >= 0:
            self.relation_combo.setCurrentIndex(idx)

        self.role_selector = RoleSelector()
        self.role_selector.set_selected(roles)

        root.addLayout(_field("ID", self.id_input))
        root.addLayout(_field("Họ và tên", self.name_input))
        root.addLayout(_field("Số điện thoại", self.phone_input))
        root.addLayout(_field("Quan hệ", self.relation_combo))
        root.addWidget(self.role_selector)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        save_btn   = QPushButton("Lưu thay đổi")
        cancel_btn = QPushButton("Hủy")
        cancel_btn.setProperty("class", "secondary")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def get_data(self):
        """
        /**
         * Chức năng: Trả về dữ liệu người dùng đã nhập trong dialog sau khi accept.
         * Tham số: Không
         * Trả về: tuple (contact_id, name, phone, relation, roles)
         */
        """
        return (
            self.id_input.text().strip(),
            self.name_input.text().strip(),
            self.phone_input.text().strip(),
            self.relation_combo.currentText(),
            self.role_selector.get_selected(),
        )


# ─────────────────────────────────────────
# DATA PAGE
# ─────────────────────────────────────────

class DataPage(QWidget):

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo trang Dữ Liệu Hệ Thống — dựng UI, tải danh bạ và nhật ký,
         *            kết nối các signal add_contact_request và log_updated.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi setup_ui() để dựng giao diện 3 tab.
         *   2. Kết nối nút Thêm, signal thêm từ ESP32, signal cập nhật nhật ký.
         *   3. Tải danh bạ và nhật ký từ database.
         */
        """
        super().__init__()
        self._log_tab_index = 2
        self.setup_ui()
        self.save_btn.clicked.connect(self.save_contact)
        bus.add_contact_request.connect(self.handle_add_contact)
        bus.log_updated.connect(self._on_log_updated, Qt.QueuedConnection)
        self._last_ac_packet_id = ""
        self.load_contacts()
        self.load_logs()

    # =====================================
    # UI
    # =====================================

    def setup_ui(self):
        """
        /**
         * Chức năng: Dựng toàn bộ giao diện — tiêu đề, thanh tab 3 nút và
         *            QStackedWidget chứa trang danh bạ, trang thêm mới, trang nhật ký.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo outer layout với header và tab bar.
         *   2. Tạo QStackedWidget từ 3 trang: contact, add, log.
         *   3. Gọi _switch_tab(0) để hiển thị tab Danh Bạ mặc định.
         */
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # ─────────────────────────────────
        # PAGE HEADER
        # ─────────────────────────────────
        page_title = QLabel("Dữ Liệu Hệ Thống")
        page_title.setObjectName("pageTitle")
        page_sub = QLabel("Quản lý danh bạ liên hệ và xem nhật ký sự kiện")
        page_sub.setObjectName("pageSub")
        outer.addWidget(page_title)
        outer.addWidget(page_sub)

        # ─────────────────────────────────
        # TAB BAR
        # ─────────────────────────────────
        tab_bar = QFrame()
        tab_bar.setStyleSheet(
            "QFrame { background: white; border-bottom: 1px solid #e8edf2; }"
        )
        tab_bar.setFixedHeight(48)
        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(8, 0, 8, 0)
        tab_layout.setSpacing(0)

        self.contact_btn = self._make_tab_btn("Danh Bạ")
        self.add_btn     = self._make_tab_btn("Thêm Liên Hệ")
        self.log_btn     = self._make_tab_btn("Nhật Ký")

        self.contact_btn.clicked.connect(lambda: self._switch_tab(0))
        self.add_btn.clicked.connect(lambda: self._switch_tab(1))
        self.log_btn.clicked.connect(lambda: self._switch_tab(2))

        self._tab_btns = [self.contact_btn, self.add_btn, self.log_btn]

        tab_layout.addWidget(self.contact_btn)
        tab_layout.addWidget(self.add_btn)
        tab_layout.addWidget(self.log_btn)
        tab_layout.addStretch()
        outer.addWidget(tab_bar)

        # ─────────────────────────────────
        # PAGES
        # ─────────────────────────────────
        self.pages = QStackedWidget()
        self.pages.addWidget(self._create_contact_page())
        self.pages.addWidget(self._create_add_page())
        self.pages.addWidget(self._create_log_page())
        outer.addWidget(self.pages, 1)

        self._switch_tab(0)

    # ─────────────────────────────────────────
    # CONTACT PAGE
    # ─────────────────────────────────────────

    def _create_contact_page(self):
        """
        /**
         * Chức năng: Tạo trang tab Danh Bạ — QTableWidget 7 cột (ID, Tên, SĐT, Quan hệ,
         *            Vai trò, nút Sửa, nút Xóa) với resize mode cố định.
         * Tham số: Không
         * Trả về: QWidget trang danh bạ
         */
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)

        self.contact_table = QTableWidget()
        self.contact_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.contact_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.contact_table.setAlternatingRowColors(True)
        self.contact_table.verticalHeader().setVisible(False)
        self.contact_table.setColumnCount(7)
        self.contact_table.setHorizontalHeaderLabels(
            ["ID", "HỌ TÊN", "SỐ ĐT", "QUAN HỆ", "VAI TRÒ", "SỬA", "XÓA"]
        )
        hh = self.contact_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        hh.setSectionResizeMode(6, QHeaderView.Fixed)
        self.contact_table.setColumnWidth(5, 72)
        self.contact_table.setColumnWidth(6, 72)
        vh = self.contact_table.verticalHeader()
        vh.setDefaultSectionSize(44)
        vh.setMinimumSectionSize(44)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        layout.addWidget(self.contact_table)
        return page

    # ─────────────────────────────────────────
    # ADD PAGE
    # ─────────────────────────────────────────

    def _create_add_page(self):
        """
        /**
         * Chức năng: Tạo trang tab Thêm Liên Hệ — form 2 cột (trái: ID/tên/SĐT/quan hệ;
         *            phải: vai trò) bên trong card có footer chứa nút Thêm Liên Hệ.
         * Tham số: Không
         * Trả về: QWidget trang thêm liên hệ
         */
        """
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 12, 0, 0)
        page_layout.setSpacing(0)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ── Header ──
        card_hdr = QFrame()
        card_hdr.setObjectName("cardHeader")
        chdr_layout = QHBoxLayout(card_hdr)
        chdr_layout.setContentsMargins(20, 12, 20, 12)
        chdr_lbl = QLabel("THÊM LIÊN HỆ MỚI")
        chdr_lbl.setObjectName("cardTitle")
        chdr_layout.addWidget(chdr_lbl)
        card_layout.addWidget(card_hdr)

        # ── Body 2 cột ──
        body = QWidget()
        body.setStyleSheet("background: white;")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 12)
        body_layout.setSpacing(40)

        def _field(label_text, widget):
            lbl = QLabel(label_text)
            lbl.setObjectName("formLabel")
            col = QVBoxLayout()
            col.setSpacing(5)
            col.addWidget(lbl)
            col.addWidget(widget)
            return col

        self.id_input       = QLineEdit()
        self.name_input     = QLineEdit()
        self.phone_input    = QLineEdit()
        self.relation_combo = QComboBox()

        self.id_input.setPlaceholderText("Ví dụ: KH001")
        self.name_input.setPlaceholderText("Họ và tên đầy đủ")
        self.phone_input.setPlaceholderText("0xxxxxxxxx  (10 chữ số)")
        self.relation_combo.addItems([
            "Con trai", "Con gái", "Vợ", "Chồng",
            "Anh trai", "Chị gái", "Em trai", "Em gái",
            "Người chăm sóc", "Hàng xóm", "Bạn bè", "Khác",
        ])

        left = QVBoxLayout()
        left.setSpacing(14)
        left.addLayout(_field("Mã ID *",          self.id_input))
        left.addLayout(_field("Họ và tên",         self.name_input))
        left.addLayout(_field("Số điện thoại *",   self.phone_input))
        left.addLayout(_field("Quan hệ",           self.relation_combo))
        left.addStretch()

        # Cột phải: label "Vai trò" dùng formLabel, cách xuống 1 field so với trái
        self.role_selector = RoleSelector()
        self.role_selector.setTitle("")  # bỏ title của QGroupBox

        role_lbl = QLabel("Vai trò")
        role_lbl.setObjectName("formLabel")

        right = QVBoxLayout()
        right.setSpacing(5)
        right.addSpacing(58)   # căn xuống dưới field "Mã ID"
        right.addWidget(role_lbl)
        right.addWidget(self.role_selector)
        right.addStretch()

        body_layout.addLayout(left,  1)
        body_layout.addLayout(right, 1)
        card_layout.addWidget(body, 1)

        # ── Footer cố định — luôn hiển thị ở đáy card ──
        footer = QFrame()
        footer.setStyleSheet(
            "QFrame { background: #f8fafc; border-top: 1px solid #e8edf2; }"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 14, 24, 14)
        footer_layout.setSpacing(16)

        required_note = QLabel("* Mã ID và Số điện thoại là bắt buộc")
        required_note.setStyleSheet(
            "font-size: 12px; color: #95a5a6; background: transparent; border: none;"
        )

        self.save_btn = QPushButton("Thêm Liên Hệ")
        self.save_btn.setFixedSize(160, 40)

        footer_layout.addWidget(required_note)
        footer_layout.addStretch()
        footer_layout.addWidget(self.save_btn)
        card_layout.addWidget(footer)

        page_layout.addWidget(card, 1)
        return page

    # ─────────────────────────────────────────
    # LOG PAGE
    # ─────────────────────────────────────────

    def _create_log_page(self):
        """
        /**
         * Chức năng: Tạo trang tab Nhật Ký — toolbar (Làm Mới, Xóa Nhật Ký) và
         *            QTextEdit readonly hiển thị log màu sắc theo loại sự kiện.
         * Tham số: Không
         * Trả về: QWidget trang nhật ký
         */
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        refresh_btn = QPushButton("Làm Mới")
        refresh_btn.setFixedHeight(36)
        refresh_btn.setProperty("class", "secondary")
        refresh_btn.clicked.connect(self.load_logs)
        clear_btn = QPushButton("Xóa Nhật Ký")
        clear_btn.setFixedHeight(36)
        clear_btn.setProperty("class", "danger")
        clear_btn.clicked.connect(self._clear_logs)
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(clear_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "QTextEdit { font-family: 'Consolas', monospace; font-size: 12px; }"
        )
        layout.addWidget(self.log_text)
        return page

    # =====================================
    # LOAD DATA
    # =====================================

    def load_contacts(self):
        """
        /**
         * Chức năng: Tải danh sách liên hệ từ database và điền vào contact_table;
         *            thêm nút Sửa và Xóa vào mỗi hàng.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi database_service.load_contacts() → list tuple.
         *   2. Set row count và điền 5 cột text (ID, tên, SĐT, quan hệ, vai trò).
         *   3. Tạo nút Sửa (edit_contact) và Xóa (delete_contact) cho mỗi hàng.
         */
        """
        contacts = database_service.load_contacts()
        self.contact_table.setRowCount(len(contacts))
        for row, contact in enumerate(contacts):
            contact_id, name, phone, relation, roles_str = contact
            for col, text in enumerate([contact_id, name, phone, relation, roles_str]):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.contact_table.setItem(row, col, item)

            edit_btn = QPushButton("✏")
            edit_btn.setFixedSize(42, 32)
            edit_btn.setToolTip("Sửa liên hệ")
            edit_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ebf5fb;
                    color: #1a6ea8;
                    border: 1.5px solid #85c1e9;
                    border-radius: 5px;
                    font-size: 16px;
                    font-weight: 700;
                    padding: 0;
                }
                QPushButton:hover {
                    background-color: #d6eaf8;
                    border-color: #2980b9;
                }
                QPushButton:pressed { background-color: #aed6f1; }
            """)
            edit_btn.clicked.connect(lambda _, r=row: self.edit_contact(r))

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(42, 32)
            del_btn.setToolTip("Xóa liên hệ")
            del_btn.setStyleSheet("""
                QPushButton {
                    background-color: #fdedec;
                    color: #c0392b;
                    border: 1.5px solid #f1948a;
                    border-radius: 5px;
                    font-size: 16px;
                    font-weight: 700;
                    padding: 0;
                }
                QPushButton:hover {
                    background-color: #fadbd8;
                    border-color: #e74c3c;
                }
                QPushButton:pressed { background-color: #f1948a; }
            """)
            del_btn.clicked.connect(lambda _, r=row: self.delete_contact(r))

            self.contact_table.setCellWidget(row, 5, self._center_widget(edit_btn))
            self.contact_table.setCellWidget(row, 6, self._center_widget(del_btn))

    def load_logs(self):
        """
        /**
         * Chức năng: Tải nhật ký từ database và hiển thị dưới dạng HTML màu sắc
         *            theo loại sự kiện (SOS, khẩn cấp, nguy hiểm, SMS, ...).
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi database_service.load_logs() → list (timestamp, message) DESC.
         *   2. Đảo lại thứ tự (cũ→mới), tô màu theo từ khóa đặc trưng trong message.
         *   3. Render HTML vào log_text và cuộn xuống cuối.
         */
        """
        logs = database_service.load_logs()
        self.log_text.clear()
        if not logs:
            self.log_text.setPlainText("Chưa có dữ liệu nhật ký.")
            return

        parts = []
        # logs trả về DESC (mới nhất trước) — đảo lại để hiển thị cũ→mới
        for timestamp, message in reversed(logs):
            ts = _html.escape(timestamp[:16])
            msg = _html.escape(message)

            if "[SOS]" in message:
                color, bg = "#c0392b", "background:#fff0f0;"
            elif "🚨" in message or "KHẨN CẤP" in message:
                color, bg = "#c0392b", "background:#fff5f5;"
            elif "🔴" in message or "NGUY HIỂM" in message:
                color, bg = "#d35400", "background:#fff8f0;"
            elif "🟡" in message or "CẦN HỖ TRỢ" in message:
                color, bg = "#7d6608", "background:#fffdf0;"
            elif "🟢" in message or "NHU CẦU" in message:
                color, bg = "#1e8449", "background:#f0fff4;"
            elif "[SMS ĐI] Thành công" in message or "Đã nhận" in message:
                color, bg = "#1a5276", ""
            elif "[SMS ĐẾN]" in message or "[TIN NHANH]" in message:
                color, bg = "#6c3483", ""
            elif "[CẢNH BÁO]" in message or "lỗi" in message.lower():
                color, bg = "#d35400", "background:#fff8f0;"
            elif "[SMS ĐI]" in message:
                color, bg = "#c0392b", ""
            elif "[DELIVERY]" in message:
                color, bg = "#1a5276", ""
            elif "[MANUAL SMS]" in message:
                color, bg = "#5d6d7e", ""
            else:
                color, bg = "#5d6d7e", ""

            parts.append(
                f'<div style="padding:3px 8px; border-bottom:1px solid #f0f4f8; {bg}">'
                f'<span style="color:#95a5a6; font-size:12px;">[{ts}]</span> '
                f'<span style="color:{color}; font-size:13px;">{msg}</span>'
                f'</div>'
            )

        self.log_text.setHtml(
            '<div style="font-family: Consolas, monospace; line-height:1.5;">'
            + "".join(parts)
            + '</div>'
        )
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # =====================================
    # SAVE CONTACT (UI form)
    # =====================================

    def save_contact(self):
        """
        /**
         * Chức năng: Validate và lưu liên hệ mới từ form UI vào database, đồng bộ lên ESP32,
         *            tải lại bảng và chuyển về tab Danh Bạ.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy dữ liệu từ form; validate ID, SĐT (10 chữ số bắt đầu 0).
         *   2. Gọi database_service.add_contact(); hiện cảnh báo nếu thất bại.
         *   3. Xóa form, gọi uart_service.push_contact() và load_contacts(), load_logs().
         *   4. Chuyển sang tab 0 (Danh Bạ).
         */
        """
        contact_id = self.id_input.text().strip()
        name       = self.name_input.text().strip()
        phone      = self.phone_input.text().strip()
        relation   = self.relation_combo.currentText()
        roles      = self.role_selector.get_selected()

        if not contact_id:
            QMessageBox.warning(self, "LỖI", "Vui lòng nhập Mã ID")
            return
        if not phone:
            QMessageBox.warning(self, "LỖI", "Vui lòng nhập số điện thoại")
            return
        if not re.match(r'^0\d{9}$', phone):
            QMessageBox.warning(
                self, "LỖI",
                "Số điện thoại không hợp lệ\n(10 chữ số, bắt đầu bằng 0)"
            )
            return

        success, reason = database_service.add_contact(
            contact_id, name, phone, relation, roles
        )
        if not success:
            QMessageBox.warning(self, "LỖI", reason)
            return

        self.id_input.clear()
        self.name_input.clear()
        self.phone_input.clear()
        self.relation_combo.setCurrentIndex(0)
        self.role_selector.clear()

        uart_service.push_contact(contact_id, name, phone, relation)
        self.load_contacts()
        self.load_logs()
        QMessageBox.information(self, "THÀNH CÔNG", "Đã lưu liên hệ thành công")
        self._switch_tab(0)

    # =====================================
    # ADD CONTACT FROM ESP32
    # =====================================

    def handle_add_contact(self, payload):
        """
        /**
         * Chức năng: Xử lý yêu cầu thêm liên hệ gửi từ ESP32 qua signal add_contact_request;
         *            chống xử lý trùng packet_id.
         * Tham số:
         *   payload : dict chứa "id", "phone" và "_packet_id"
         * Trả về: None
         * Luồng hoạt động:
         *   1. Kiểm tra _packet_id trùng với lần xử lý trước → bỏ qua nếu trùng.
         *   2. Gọi database_service.add_contact(); gửi kết quả SUCCESS/FAILED về ESP32.
         *   3. Đẩy liên hệ lên ESP32 và tải lại bảng.
         */
        """
        payload   = dict(payload)
        packet_id = payload.pop("_packet_id", "")
        if packet_id and packet_id == self._last_ac_packet_id:
            return
        self._last_ac_packet_id = packet_id

        contact_id = payload.get("id", "")
        phone      = payload.get("phone", "")
        success, reason = database_service.add_contact(
            contact_id, "", phone, "", "ƯU TIÊN"
        )
        if success:
            uart_service.send_contact_result("SUCCESS")
            uart_service.push_contact(contact_id, "", phone, "")
        else:
            uart_service.send_contact_result("FAILED", reason)
        self.load_contacts()
        self.load_logs()

    # =====================================
    # DELETE CONTACT
    # =====================================

    def delete_contact(self, row):
        """
        /**
         * Chức năng: Xóa liên hệ tại hàng chỉ định — hỏi xác nhận, xóa DB, đồng bộ ESP32
         *            và hủy các packet SMS đang retry cho số điện thoại này.
         * Tham số:
         *   row : chỉ số hàng trong contact_table
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy contact_id và phone từ bảng; hiện dialog xác nhận.
         *   2. Xóa database, push_delete_contact tới ESP32.
         *   3. Duyệt _sms_pending và hủy packet có phone khớp.
         */
        """
        item = self.contact_table.item(row, 0)
        if item is None:
            return
        contact_id = item.text()

        phone_item = self.contact_table.item(row, 2)
        phone = phone_item.text() if phone_item else ""

        reply = QMessageBox.question(
            self, "Xác Nhận Xóa",
            f"Bạn có chắc muốn xóa liên hệ  «{contact_id}»  không?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        database_service.delete_contact(contact_id)
        uart_service.push_delete_contact(contact_id)

        # Hủy ngay các packet SMS đang chờ retry cho số điện thoại này
        if phone:
            from ai.keyword_engine import _sms_pending
            for pid in list(_sms_pending.keys()):
                pkt_phone = _sms_pending[pid]["packet"].get("payload", {}).get("phone", "")
                if pkt_phone == phone:
                    _sms_pending.pop(pid, None)

        self.load_contacts()
        self.load_logs()

    # =====================================
    # EDIT CONTACT
    # =====================================

    def edit_contact(self, row):
        """
        /**
         * Chức năng: Mở EditContactDialog với dữ liệu hàng hiện tại; nếu người dùng
         *            xác nhận thì validate, cập nhật DB, đồng bộ ESP32 và tải lại bảng.
         * Tham số:
         *   row : chỉ số hàng trong contact_table
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đọc 4 cột (ID, tên, SĐT, quan hệ) và vai trò từ DB.
         *   2. Hiện EditContactDialog; trả về nếu người dùng hủy.
         *   3. Validate SĐT mới; gọi database_service.update_contact().
         *   4. Push xóa ID cũ + thêm ID mới lên ESP32, tải lại bảng.
         */
        """
        item = self.contact_table.item(row, 0)
        if item is None:
            return
        old_id       = self.contact_table.item(row, 0).text()
        old_name     = self.contact_table.item(row, 1).text()
        old_phone    = self.contact_table.item(row, 2).text()
        old_relation = self.contact_table.item(row, 3).text()
        old_roles    = database_service.get_contact_roles(old_id)

        dialog = EditContactDialog(
            old_id, old_name, old_phone, old_relation, old_roles, self
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        new_id, new_name, new_phone, new_relation, new_roles = dialog.get_data()

        if not new_id:
            QMessageBox.warning(self, "LỖI", "Vui lòng nhập Mã ID")
            return
        if not re.match(r'^0\d{9}$', new_phone):
            QMessageBox.warning(
                self, "LỖI",
                "Số điện thoại không hợp lệ\n(10 chữ số, bắt đầu bằng 0)"
            )
            return

        success, reason = database_service.update_contact(
            old_id, new_id, new_name, new_phone, new_relation, new_roles
        )
        if not success:
            QMessageBox.warning(self, "LỖI", reason)
            return

        uart_service.push_delete_contact(old_id)
        uart_service.push_contact(new_id, new_name, new_phone, new_relation)
        self.load_contacts()
        self.load_logs()
        QMessageBox.information(self, "THÀNH CÔNG", "Đã cập nhật liên hệ")

    # =====================================
    # HELPERS
    # =====================================

    def _clear_logs(self):
        """
        /**
         * Chức năng: Hỏi xác nhận rồi xóa toàn bộ nhật ký trong DB và log_text.
         * Tham số: Không
         * Trả về: None
         */
        """
        reply = QMessageBox.question(
            self, "Xác Nhận",
            "Bạn có chắc muốn xóa toàn bộ nhật ký không?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        database_service.clear_logs()
        self.log_text.clear()

    def _make_tab_btn(self, text: str) -> QPushButton:
        """
        /**
         * Chức năng: Tạo QPushButton dùng làm tab với property "class"="tab" và
         *            "active"=False, dùng Qt stylesheet selector để tô màu active.
         * Tham số:
         *   text : nhãn hiển thị trên nút
         * Trả về: QPushButton đã cấu hình
         */
        """
        btn = QPushButton(text)
        btn.setProperty("class", "tab")
        btn.setProperty("active", False)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _on_log_updated(self):
        """
        /**
         * Chức năng: Tự động tải lại nhật ký khi tab Nhật Ký đang hiển thị và
         *            có sự kiện log_updated từ bus.
         * Tham số: Không
         * Trả về: None
         */
        """
        if self.pages.currentIndex() == self._log_tab_index:
            self.load_logs()

    def _switch_tab(self, index: int):
        """
        /**
         * Chức năng: Chuyển tab đang hiển thị — cập nhật property "active" cho tất cả
         *            tab button và tải lại nhật ký nếu chuyển sang tab Nhật Ký.
         * Tham số:
         *   index : chỉ số tab cần chuyển đến (0=Danh Bạ, 1=Thêm, 2=Nhật Ký)
         * Trả về: None
         */
        """
        for i, btn in enumerate(self._tab_btns):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.pages.setCurrentIndex(index)
        if index == self._log_tab_index:
            self.load_logs()

    @staticmethod
    def _center_widget(widget: QWidget) -> QWidget:
        """
        /**
         * Chức năng: Bọc widget trong QWidget wrapper có layout căn giữa —
         *            dùng để đặt nút Sửa/Xóa vào giữa ô bảng.
         * Tham số:
         *   widget : widget cần căn giữa
         * Trả về: QWidget wrapper chứa widget căn giữa
         */
        """
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(widget)
        return wrapper
