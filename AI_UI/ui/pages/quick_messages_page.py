from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QFrame, QScrollArea,
    QMessageBox, QTextEdit,
)
from PyQt5.QtCore import Qt, pyqtSlot

from services.database_service import database_service
from services.tts_service import tts_service
from core.event_bus import bus


# ─────────────────────────────────────────────────────────
# TIN NHẮN MẪU
# ─────────────────────────────────────────────────────────

TEMPLATES = {
    "elderly": {
        "label": "Mẫu Người Già",
        "description": "Nội dung đơn giản, quan tâm sức khỏe & nhắc nhở sinh hoạt",
        "color":   "#8e44ad",
        "hover":   "#7d3c98",
        "pressed": "#6c3483",
        "messages": {
            1:  "Con hỏi thăm sức khỏe của ông bà",
            2:  "Hôm nay con về muộn, đừng lo nhé",
            3:  "Đã đến giờ uống thuốc",
            4:  "Con đang trên đường về nhà",
            5:  "Hôm nay trời lạnh, nhớ mặc ấm nhé",
            6:  "Đã đến giờ ăn cơm",
            7:  "Mọi chuyện bình thường, không cần lo lắng",
            8:  "Con sẽ đến thăm vào cuối tuần",
            9:  "Bình tĩnh, gọi cho con nếu cần giúp đỡ",
            10: "Con yêu ông bà rất nhiều",
        },
    },
    "child": {
        "label": "Mẫu Trẻ Em",
        "description": "Nội dung vui vẻ, động viên & nhắc nhở sinh hoạt hằng ngày",
        "color":   "#2980b9",
        "hover":   "#2471a3",
        "pressed": "#1a5276",
        "messages": {
            1:  "Ba mẹ yêu con nhiều lắm",
            2:  "Đến giờ ăn cơm rồi nhé",
            3:  "Đến giờ làm bài tập rồi",
            4:  "Đến giờ đi ngủ rồi nhé",
            5:  "Ba mẹ sắp về nhà rồi",
            6:  "Nhớ uống nước nhiều vào nhé",
            7:  "Nghỉ ngơi một chút thôi nhé",
            8:  "Ba mẹ đang nhớ con rất nhiều",
            9:  "Con giỏi lắm, cố lên nhé",
            10: "Đến giờ tập thể dục rồi",
        },
    },
}


class QuickMessagesPage(QWidget):
    """
    Trang cài đặt Tin Nhắn Nhanh (slot 1–10).

    Luồng:
        Người thân gửi SMS số 1-10 → ESP32 → NEW_SMS signal
        → ai_page nhận → kiểm tra nội dung là số 1-10
        → gọi database_service.get_quick_message(slot)
        → tts_service.speak(text)
    """

    NUM_SLOTS = 10

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo trang Tin Nhắn Nhanh — setup UI, tải dữ liệu từ DB
         *            và kết nối signal quick_message_triggered.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Khởi tạo dict _inputs[slot] = QLineEdit.
         *   2. Gọi _setup_ui() để dựng giao diện.
         *   3. Gọi _load_data() để tải nội dung slot từ database.
         *   4. Kết nối bus.quick_message_triggered → _on_triggered để cập nhật nhật ký.
         */
        """
        super().__init__()
        # inputs[slot] = QLineEdit
        self._inputs: dict[int, QLineEdit] = {}
        self._setup_ui()
        self._load_data()

        # Nhận tín hiệu từ ai_page khi quick message được kích hoạt
        bus.quick_message_triggered.connect(
            self._on_triggered, Qt.QueuedConnection
        )

    # ─────────────────────────────────────────────
    # UI
    # ─────────────────────────────────────────────

    def _setup_ui(self):
        """
        /**
         * Chức năng: Dựng toàn bộ giao diện trang — header, card cài đặt nội dung
         *            (thanh template, scroll 10 slot, nút Lưu) và card nhật ký.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo layout outer, thêm tiêu đề và mô tả.
         *   2. Tạo card cài đặt với template bar và 10 hàng slot cuộn.
         *   3. Thêm footer với nút "Lưu Tất Cả".
         *   4. Tạo card nhật ký kích hoạt với QTextEdit readonly.
         */
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # ── HEADER ──────────────────────────────
        title = QLabel("Tin Nhắn Nhanh")
        title.setObjectName("pageTitle")
        sub = QLabel(
            "Người thân gửi SMS số 1–10 → hệ thống tự động phát âm thanh đoạn văn bản tương ứng"
        )
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        # ── CARD: CÀI ĐẶT NỘI DUNG ─────────────
        edit_card = QFrame()
        edit_card.setObjectName("card")
        edit_card_layout = QVBoxLayout(edit_card)
        edit_card_layout.setContentsMargins(0, 0, 0, 0)
        edit_card_layout.setSpacing(0)

        # ── Card header ──
        hdr = QFrame()
        hdr.setObjectName("cardHeader")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 10, 16, 10)
        hdr_lbl = QLabel("CÀI ĐẶT NỘI DUNG")
        hdr_lbl.setObjectName("cardTitle")
        hdr_layout.addWidget(hdr_lbl)
        hdr_layout.addStretch()

        hint = QLabel("Nhập nội dung văn bản cho từng số, bấm Lưu để cập nhật")
        hint.setObjectName("pageSub")
        hint.setStyleSheet("font-size:13px; color:#95a5a6; background:transparent;")
        hdr_layout.addWidget(hint)
        edit_card_layout.addWidget(hdr)

        # ── Thanh tin nhắn mẫu ──────────────────
        template_bar = QFrame()
        template_bar.setStyleSheet(
            "QFrame { background: #f0f4f8; border-bottom: 1px solid #e8edf2; }"
        )
        template_layout = QHBoxLayout(template_bar)
        template_layout.setContentsMargins(16, 8, 16, 8)
        template_layout.setSpacing(10)

        tmpl_lbl = QLabel("Điền nhanh tin nhắn mẫu:")
        tmpl_lbl.setStyleSheet(
            "font-size:13px; font-weight:600; color:#555; background:transparent;"
        )
        template_layout.addWidget(tmpl_lbl)

        for key, tmpl in TEMPLATES.items():
            btn = QPushButton(f"  {tmpl['label']}")
            btn.setMinimumHeight(30)
            btn.setMinimumWidth(150)
            btn.setToolTip(tmpl["description"])
            btn.setStyleSheet(
                f"QPushButton {{ background-color:{tmpl['color']}; color:white;"
                f" font-weight:700; border-radius:5px; padding:0 12px; font-size:13px; }}"
                f"QPushButton:hover {{ background-color:{tmpl['hover']}; }}"
                f"QPushButton:pressed {{ background-color:{tmpl['pressed']}; }}"
            )
            btn.clicked.connect(lambda _, k=key: self._apply_template(k))
            template_layout.addWidget(btn)

        template_layout.addStretch()
        edit_card_layout.addWidget(template_bar)

        # ── Scroll area chứa 10 hàng ────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        slots_widget = QWidget()
        slots_widget.setStyleSheet("background: white;")
        slots_layout = QVBoxLayout(slots_widget)
        slots_layout.setContentsMargins(16, 12, 16, 12)
        slots_layout.setSpacing(10)

        for slot in range(1, self.NUM_SLOTS + 1):
            row = self._make_slot_row(slot)
            slots_layout.addWidget(row)

        slots_layout.addStretch()
        scroll.setWidget(slots_widget)
        edit_card_layout.addWidget(scroll, 1)

        # Footer: nút Lưu
        footer = QFrame()
        footer.setStyleSheet(
            "background:#f8fafc; border-top:1px solid #e8edf2;"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 10)
        footer_layout.addStretch()

        self._save_btn = QPushButton("  Lưu Tất Cả")
        self._save_btn.setFixedWidth(150)
        self._save_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; font-weight: 700; border-radius: 5px; }"
            "QPushButton:hover { background-color: #1e8449; }"
            "QPushButton:pressed { background-color: #196f3d; }"
        )
        self._save_btn.clicked.connect(self._save_all)
        footer_layout.addWidget(self._save_btn)

        edit_card_layout.addWidget(footer)
        outer.addWidget(edit_card, 1)

        # ── CARD: NHẬT KÝ KÍCH HOẠT ─────────────
        log_card = QFrame()
        log_card.setObjectName("card")
        log_card.setFixedHeight(180)
        log_card_layout = QVBoxLayout(log_card)
        log_card_layout.setContentsMargins(0, 0, 0, 0)
        log_card_layout.setSpacing(0)

        log_hdr = QFrame()
        log_hdr.setObjectName("cardHeader")
        log_hdr_layout = QHBoxLayout(log_hdr)
        log_hdr_layout.setContentsMargins(16, 10, 16, 10)
        log_hdr_lbl = QLabel("NHẬT KÝ KÍCH HOẠT")
        log_hdr_lbl.setObjectName("cardTitle")
        log_hdr_layout.addWidget(log_hdr_lbl)
        log_hdr_layout.addStretch()

        clear_log_btn = QPushButton("Xóa")
        clear_log_btn.setFixedSize(50, 24)
        clear_log_btn.setProperty("class", "secondary")
        clear_log_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #95a5a6;
                border: 1px solid #d5dde5; border-radius: 3px;
                font-size: 12px; padding: 0;
            }
            QPushButton:hover { background: #fdedec; color: #c0392b; border-color: #e74c3c; }
        """)
        clear_log_btn.clicked.connect(self._clear_log)
        log_hdr_layout.addWidget(clear_log_btn)
        log_card_layout.addWidget(log_hdr)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(
            "QTextEdit { border: none; border-radius: 0; font-size: 14px; "
            "font-family: 'Consolas', monospace; padding: 6px 12px; }"
        )
        log_card_layout.addWidget(self._log_text, 1)

        outer.addWidget(log_card)

    def _make_slot_row(self, slot: int) -> QFrame:
        """
        /**
         * Chức năng: Tạo một hàng UI cho slot: badge số | input | nút Lưu | nút Thử.
         * Tham số:
         *   slot : số slot (1-10)
         * Trả về: QFrame chứa các widget của hàng
         * Luồng hoạt động:
         *   1. Tạo QFrame hàng ngang với badge số, label, QLineEdit, nút Lưu, nút Thử.
         *   2. Kết nối editingFinished → _auto_save_slot, clicked Lưu → _save_slot,
         *      clicked Thử → _test_slot.
         *   3. Lưu QLineEdit vào self._inputs[slot].
         */
        """
        row = QFrame()
        row.setStyleSheet(
            "QFrame { background: white; border: none; "
            "border-bottom: 1px solid #f0f4f8; } "
            "QFrame:last-child { border-bottom: none; }"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)

        # Badge số
        badge = QLabel(str(slot))
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            "QLabel { background-color: #3498db; color: white; "
            "border-radius: 17px; font-weight: 700; font-size: 15px; }"
        )
        layout.addWidget(badge)

        # Label
        lbl = QLabel(f"Nội dung #{slot}:")
        lbl.setObjectName("formLabel")
        lbl.setFixedWidth(110)
        layout.addWidget(lbl)

        # Input
        inp = QLineEdit()
        inp.setPlaceholderText(f"Nhập đoạn văn bản sẽ phát khi nhận SMS \"{slot}\"...")
        inp.setMinimumHeight(36)
        inp.editingFinished.connect(lambda s=slot: self._auto_save_slot(s))
        layout.addWidget(inp, 1)
        self._inputs[slot] = inp

        # Nút Lưu
        save_btn = QPushButton("Lưu")
        save_btn.setMinimumWidth(80)
        save_btn.setMinimumHeight(36)
        save_btn.setToolTip(f"Lưu nội dung slot #{slot} vào database")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; font-weight: 700;"
            " border-radius: 5px; padding: 0 14px; font-size: 15px; }"
            "QPushButton:hover { background-color: #1e8449; }"
            "QPushButton:pressed { background-color: #196f3d; }"
        )
        save_btn.clicked.connect(lambda _, s=slot: self._save_slot(s))
        layout.addWidget(save_btn)

        # Nút Test
        test_btn = QPushButton("Thử")
        test_btn.setMinimumWidth(80)
        test_btn.setMinimumHeight(36)
        test_btn.setToolTip(f"Phát thử nội dung slot #{slot}")
        test_btn.setStyleSheet(
            "QPushButton { background-color: #e67e22; color: white; font-weight: 700;"
            " border-radius: 5px; padding: 0 14px; font-size: 15px; }"
            "QPushButton:hover { background-color: #ca6f1e; }"
            "QPushButton:pressed { background-color: #a04000; }"
        )
        test_btn.clicked.connect(lambda _, s=slot: self._test_slot(s))
        layout.addWidget(test_btn)

        return row

    # ─────────────────────────────────────────────
    # TEMPLATE
    # ─────────────────────────────────────────────

    def _apply_template(self, key: str):
        """
        /**
         * Chức năng: Điền 10 slot theo mẫu đã chọn — hỏi người dùng nếu đã có nội dung.
         * Tham số:
         *   key : key của template trong TEMPLATES ("elderly" hoặc "child")
         * Trả về: None
         * Luồng hoạt động:
         *   1. Kiểm tra xem có slot nào đang có nội dung không.
         *   2. Nếu có: hiện dialog chọn "Thay tất cả" / "Chỉ điền chỗ trống" / "Hủy".
         *   3. Điền và lưu database từng slot theo lựa chọn.
         *   4. Ghi log số slot đã điền.
         */
        """
        tmpl = TEMPLATES[key]
        messages = tmpl["messages"]

        # Kiểm tra xem có slot nào đang có nội dung không
        has_content = any(
            self._inputs[s].text().strip()
            for s in range(1, self.NUM_SLOTS + 1)
        )

        fill_all = True
        if has_content:
            box = QMessageBox(self)
            box.setWindowTitle(f"Áp dụng {tmpl['label']}")
            box.setText(
                "Một số slot đã có nội dung.\n"
                "Bạn muốn xử lý như thế nào?"
            )
            btn_all    = box.addButton("Thay tất cả",        QMessageBox.AcceptRole)
            btn_empty  = box.addButton("Chỉ điền chỗ trống", QMessageBox.YesRole)
            btn_cancel = box.addButton("Hủy",                QMessageBox.RejectRole)
            box.setDefaultButton(btn_empty)
            box.exec_()

            clicked = box.clickedButton()
            if clicked is btn_cancel:
                return
            fill_all = (clicked is btn_all)

        filled = 0
        for slot in range(1, self.NUM_SLOTS + 1):
            inp = self._inputs[slot]
            if fill_all or not inp.text().strip():
                text = messages.get(slot, "")
                inp.setText(text)
                database_service.save_quick_message(slot, text)
                filled += 1

        self._append_log(
            "MẪU",
            f"Đã điền và lưu {filled} slot theo \"{tmpl['label']}\""
        )

    # ─────────────────────────────────────────────
    # DATA
    # ─────────────────────────────────────────────

    def _load_data(self):
        """
        /**
         * Chức năng: Tải nội dung tất cả slot từ database và điền vào QLineEdit tương ứng.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi database_service.load_quick_messages() → dict {slot: text}.
         *   2. Điền text vào self._inputs[slot] cho mỗi slot.
         */
        """
        data = database_service.load_quick_messages()
        for slot, text in data.items():
            if slot in self._inputs:
                self._inputs[slot].setText(text)

    def _save_slot(self, slot: int):
        """
        /**
         * Chức năng: Lưu một slot riêng lẻ vào database ngay lập tức và ghi log kết quả.
         * Tham số:
         *   slot : số slot cần lưu (1-10)
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy text từ input[slot].
         *   2. Gọi database_service.save_quick_message() và ghi log thành công/lỗi.
         */
        """
        text = self._inputs[slot].text().strip()
        if database_service.save_quick_message(slot, text):
            if text:
                self._append_log("LƯU", f"Slot #{slot} → \"{text}\"")
            else:
                self._append_log("LƯU", f"Slot #{slot} → (xóa nội dung)")
        else:
            self._append_log("LỖI", f"Không thể lưu slot #{slot}")

    def _save_all(self):
        """
        /**
         * Chức năng: Lưu tất cả 10 slot vào database và hiện thông báo kết quả.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lặp qua 10 slot, gọi save_quick_message cho từng slot.
         *   2. Đếm slot lưu thành công; hiện QMessageBox.information hoặc warning.
         */
        """
        ok_count = 0
        for slot, inp in self._inputs.items():
            if database_service.save_quick_message(slot, inp.text()):
                ok_count += 1

        if ok_count == self.NUM_SLOTS:
            self._append_log("SYS", "Đã lưu tất cả 10 slot thành công")
            QMessageBox.information(
                self, "Lưu thành công",
                "Đã lưu 10 nội dung tin nhắn nhanh."
            )
        else:
            QMessageBox.warning(
                self, "Lỗi",
                "Có lỗi khi lưu một số slot. Kiểm tra console."
            )

    def _auto_save_slot(self, slot: int):
        """
        /**
         * Chức năng: Tự động lưu slot khi QLineEdit mất focus — silent, không ghi log.
         * Tham số:
         *   slot : số slot cần lưu
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy text từ input[slot].
         *   2. Gọi database_service.save_quick_message() không kiểm tra kết quả.
         */
        """
        text = self._inputs[slot].text().strip()
        database_service.save_quick_message(slot, text)

    # ─────────────────────────────────────────────
    # TEST
    # ─────────────────────────────────────────────

    def _test_slot(self, slot: int):
        """
        /**
         * Chức năng: Phát thử nội dung slot qua TTS để kiểm tra trước khi lưu.
         * Tham số:
         *   slot : số slot cần phát thử
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy text từ input[slot]; hiện cảnh báo nếu rỗng.
         *   2. Ghi log và gọi tts_service.speak(text).
         */
        """
        text = self._inputs[slot].text().strip()
        if not text:
            QMessageBox.warning(
                self, "Trống",
                f"Slot #{slot} chưa có nội dung. Vui lòng nhập và Lưu trước."
            )
            return
        self._append_log("TEST", f"Phát thử slot #{slot}: \"{text}\"")
        tts_service.speak(text)

    # ─────────────────────────────────────────────
    # TRIGGER SIGNAL (từ ai_page)
    # ─────────────────────────────────────────────

    @pyqtSlot(int, str, str)
    def _on_triggered(self, slot: int, sender: str, text: str):
        """
        /**
         * Chức năng: Cập nhật nhật ký và highlight input khi slot được kích hoạt bởi SMS đến.
         * Tham số:
         *   slot   : số slot được kích hoạt
         *   sender : nhãn người gửi SMS
         *   text   : nội dung slot đã được phát
         * Trả về: None
         * Luồng hoạt động:
         *   1. Ghi log sự kiện kích hoạt.
         *   2. Highlight border tím cho input tương ứng trong 3 giây.
         */
        """
        self._append_log(
            f"SMS từ {sender}",
            f"Slot #{slot} → \"{text}\""
        )
        # Highlight input tương ứng tạm thời
        inp = self._inputs.get(slot)
        if inp:
            orig_style = inp.styleSheet()
            inp.setStyleSheet(
                "QLineEdit { border: 2px solid #8e44ad; background: #f5eef8; }"
            )
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(
                3000,
                lambda: inp.setStyleSheet(orig_style)
            )

    # ─────────────────────────────────────────────
    # LOG HELPERS
    # ─────────────────────────────────────────────

    def _append_log(self, source: str, message: str):
        """
        /**
         * Chức năng: Thêm dòng log có timestamp vào QTextEdit nhật ký và cuộn xuống cuối.
         * Tham số:
         *   source  : nguồn sự kiện (ví dụ "LƯU", "TEST", "MẪU")
         *   message : nội dung dòng log
         * Trả về: None
         */
        """
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.append(f"[{ts}] [{source}] {message}")
        sb = self._log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self):
        """
        /**
         * Chức năng: Xóa toàn bộ nội dung nhật ký kích hoạt.
         * Tham số: Không
         * Trả về: None
         */
        """
        self._log_text.clear()
