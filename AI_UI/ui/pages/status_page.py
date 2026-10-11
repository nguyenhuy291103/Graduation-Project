import time
import serial.tools.list_ports

from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer

from core.state_manager import state_manager
from core.event_bus import bus
from services.uart_service import uart_service


class StatusPage(QWidget):

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo StatusPage — xây dựng giao diện, quét cổng COM,
         *            và cài các QTimer theo dõi heartbeat và timeout trạng thái.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Khởi tạo dict labels/dots rỗng và cờ _contacts_synced=False.
         *   2. Gọi setup_ui() và load_ports().
         *   3. Kết nối bus.system_state_updated → update_state().
         *   4. Tạo _hb_timer (5s) để kiểm tra heartbeat ESP32.
         *   5. Tạo _state_timeout_timer (one-shot) cho timeout SYSTEM_STATE.
         *   6. Tạo _retry_timer (one-shot) để retry request nếu chưa nhận được.
         */
        """
        super().__init__()
        self.labels = {}
        self.dots   = {}
        self._contacts_synced = False
        self.setup_ui()
        self.load_ports()
        self._heartbeat_warned = False
        bus.system_state_updated.connect(self.update_state)

        # Heartbeat watchdog — kiểm tra mỗi 5 giây
        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(5000)
        self._hb_timer.timeout.connect(self._check_heartbeat)
        self._hb_timer.start()

        # Safety-net timeout: nếu ESP32 không trả lời trong 10s → thoát "Đang kiểm tra..."
        self._state_timeout_timer = QTimer(self)
        self._state_timeout_timer.setSingleShot(True)
        self._state_timeout_timer.timeout.connect(self._on_state_timeout)

        # Retry timer: 5 giây sau khi kết nối, thử yêu cầu state lần nữa
        # (an toàn nếu lần đầu ESP32 chưa xong boot check)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry_state_request)

    # =====================================
    # UI
    # =====================================

    def setup_ui(self):
        """
        /**
         * Chức năng: Xây dựng toàn bộ giao diện StatusPage gồm card kết nối
         *            UART và card hiển thị trạng thái thiết bị ESP32/SIM.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo layout ngoài với header tên trang.
         *   2. Tạo "CONNECTION CARD" với ComboBox chọn cổng và nút kết nối/làm mới.
         *   3. Tạo "STATUS CARD" với QGridLayout hiển thị 6 chỉ số thiết bị.
         *   4. Lưu các widget dot và label vào dict self.dots/self.labels.
         */
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # ─────────────────────────────────
        # PAGE HEADER
        # ─────────────────────────────────
        page_title = QLabel("Trạng Thái Hệ Thống")
        page_title.setObjectName("pageTitle")
        page_sub = QLabel("Kết nối cổng COM và kiểm tra tình trạng thiết bị")
        page_sub.setObjectName("pageSub")
        outer.addWidget(page_title)
        outer.addWidget(page_sub)

        # ─────────────────────────────────
        # CONNECTION CARD
        # ─────────────────────────────────
        conn_card = QFrame()
        conn_card.setObjectName("card")
        conn_layout = QVBoxLayout(conn_card)
        conn_layout.setContentsMargins(0, 0, 0, 0)
        conn_layout.setSpacing(0)

        conn_hdr = QFrame()
        conn_hdr.setObjectName("cardHeader")
        conn_hdr_layout = QHBoxLayout(conn_hdr)
        conn_hdr_layout.setContentsMargins(16, 10, 16, 10)
        conn_hdr_title = QLabel("KẾT NỐI UART")
        conn_hdr_title.setObjectName("cardTitle")
        conn_hdr_layout.addWidget(conn_hdr_title)
        conn_layout.addWidget(conn_hdr)

        ctrl_layout = QHBoxLayout()
        ctrl_layout.setContentsMargins(16, 14, 16, 16)
        ctrl_layout.setSpacing(10)

        port_lbl = QLabel("Cổng COM:")
        port_lbl.setObjectName("formLabel")
        port_lbl.setFixedWidth(80)

        self.port_combo = QComboBox()
        self.port_combo.setFixedWidth(160)

        self.connect_btn = QPushButton("Kết Nối")
        self.connect_btn.setFixedWidth(130)
        self.connect_btn.setProperty("class", "success")

        self.refresh_btn = QPushButton("Làm Mới")
        self.refresh_btn.setFixedWidth(110)
        self.refresh_btn.setProperty("class", "secondary")

        self.connect_btn.clicked.connect(self.toggle_connection)
        self.refresh_btn.clicked.connect(self._on_refresh)

        ctrl_layout.addWidget(port_lbl)
        ctrl_layout.addWidget(self.port_combo)
        ctrl_layout.addSpacing(8)
        ctrl_layout.addWidget(self.connect_btn)
        ctrl_layout.addWidget(self.refresh_btn)
        ctrl_layout.addStretch()
        conn_layout.addLayout(ctrl_layout)

        outer.addWidget(conn_card)

        # ─────────────────────────────────
        # STATUS CARD
        # ─────────────────────────────────
        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)

        stat_hdr = QFrame()
        stat_hdr.setObjectName("cardHeader")
        stat_hdr_layout = QHBoxLayout(stat_hdr)
        stat_hdr_layout.setContentsMargins(16, 10, 16, 10)
        stat_hdr_title = QLabel("THÔNG TIN THIẾT BỊ")
        stat_hdr_title.setObjectName("cardTitle")
        stat_hdr_layout.addWidget(stat_hdr_title)
        status_layout.addWidget(stat_hdr)

        grid = QGridLayout()
        grid.setContentsMargins(20, 16, 20, 20)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        row_data = [
            ("ESP32",       "Thiết bị ESP32",    0, 0),
            ("MODULE SIM",  "Module SIM",         1, 0),
            ("THẺ SIM",     "Thẻ SIM",            2, 0),
            ("MẠNG",        "Đăng ký mạng",       0, 2),
            ("SÓNG",        "Cường độ sóng",       1, 2),
            ("CHẾ ĐỘ SMS",  "Chế độ SMS",         2, 2),
        ]

        for key, display, r, c in row_data:
            dot = QLabel("○")
            dot.setObjectName("dotNa")
            dot.setFixedWidth(22)
            dot.setAlignment(Qt.AlignCenter)

            name_lbl = QLabel(display)
            name_lbl.setObjectName("formLabel")
            name_lbl.setFixedWidth(130)

            val_lbl = QLabel("---")
            val_lbl.setObjectName("statusNa")

            self.dots[key]   = dot
            self.labels[key] = val_lbl

            row_w = QWidget()
            row_w.setStyleSheet("background: transparent;")
            row_inner = QHBoxLayout(row_w)
            row_inner.setContentsMargins(0, 0, 0, 0)
            row_inner.setSpacing(6)
            row_inner.addWidget(dot)
            row_inner.addWidget(name_lbl)
            row_inner.addWidget(val_lbl)

            grid.addWidget(row_w, r, c)

        status_layout.addLayout(grid)
        outer.addWidget(status_card)
        outer.addStretch()

    # =====================================
    # PORTS
    # =====================================

    def load_ports(self):
        """
        /**
         * Chức năng: Quét và điền danh sách cổng COM vào ComboBox.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Xóa danh sách cũ trong port_combo.
         *   2. Liệt kê các cổng COM hiện có và thêm vào ComboBox.
         */
        """
        self.port_combo.clear()
        for port in serial.tools.list_ports.comports():
            self.port_combo.addItem(port.device)

    # =====================================
    # HEARTBEAT WATCHDOG
    # =====================================

    def _check_heartbeat(self):
        """
        /**
         * Chức năng: Kiểm tra xem ESP32 có còn gửi heartbeat trong 30 giây
         *            qua không; hiển thị cảnh báo nếu mất heartbeat.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Bỏ qua nếu UART chưa kết nối.
         *   2. Tính thời gian từ heartbeat cuối.
         *   3. Nếu > 30s và chưa cảnh báo: cập nhật indicator "KHÔNG PHẢN HỒI".
         *   4. Nếu <= 30s và đang cảnh báo: phục hồi indicator "ĐÃ KẾT NỐI".
         */
        """
        if not state_manager.uart_connected:
            self._heartbeat_warned = False
            return

        last = state_manager.last_heartbeat
        if last == 0:
            return

        elapsed = time.time() - last
        if elapsed > 30 and not self._heartbeat_warned:
            self._heartbeat_warned = True
            self._set_indicator("ESP32", "KHÔNG PHẢN HỒI", "warn")
        elif elapsed <= 30 and self._heartbeat_warned:
            self._heartbeat_warned = False
            self._set_indicator("ESP32", "ĐÃ KẾT NỐI", "ok")

    # =====================================
    # CONNECT / DISCONNECT
    # =====================================

    def toggle_connection(self):
        """
        /**
         * Chức năng: Chuyển đổi trạng thái kết nối UART — ngắt nếu đang kết nối,
         *            kết nối cổng được chọn nếu chưa kết nối.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Nếu đang kết nối: dừng timers, ngắt UART, cập nhật UI.
         *   2. Nếu chưa kết nối: đọc cổng từ ComboBox; cảnh báo nếu không chọn.
         *   3. Gọi uart_service.connect(); nếu thành công: yêu cầu system state
         *      và khởi động timeout/retry timers.
         *   4. Hiển thị thông báo lỗi nếu kết nối thất bại.
         */
        """
        if uart_service.is_connected():
            self._state_timeout_timer.stop()
            self._retry_timer.stop()
            uart_service.disconnect()
            state_manager.waiting_system_response = False
            self.update_state()
            return

        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(
                self, "Chưa Chọn Cổng",
                "Vui lòng chọn cổng COM.\n"
                "Nhấn 'Làm Mới' để quét lại danh sách cổng."
            )
            return

        connected = uart_service.connect(port)
        if connected:
            state_manager.waiting_system_response = True
            self._contacts_synced = False
            # Dùng request_system_state (phản hồi ngay, không re-check) thay vì
            # check_system (gọi checkSIMStatus 5s trên ESP32 gây UI kẹt "Đang kiểm tra").
            # simTask đã tự chạy checkSIMStatus lúc boot và mỗi 60s nên state luôn cập nhật.
            uart_service.request_system_state()
            self.update_state()
            self._state_timeout_timer.start(10000)
            # Safety-net: nếu 5s sau vẫn chờ → yêu cầu lần nữa
            self._retry_timer.start(5000)
        else:
            QMessageBox.warning(
                self, "Kết Nối Thất Bại",
                f"Không thể kết nối tới cổng {port}.\n\n"
                "Kiểm tra:\n"
                "• ESP32 đã được cắm vào máy tính chưa\n"
                "• Cổng COM có đúng không\n"
                "• Không có chương trình nào đang dùng cổng này"
            )

    # =====================================
    # RETRY STATE REQUEST (safety-net)
    # =====================================

    def _retry_state_request(self):
        """
        /**
         * Chức năng: Gửi lại yêu cầu system state nếu sau 5s vẫn chưa nhận
         *            được phản hồi từ ESP32 (safety-net cho boot chậm).
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Kiểm tra còn kết nối và vẫn đang chờ phản hồi.
         *   2. Nếu có: gọi uart_service.request_system_state().
         */
        """
        if uart_service.is_connected() and state_manager.waiting_system_response:
            uart_service.request_system_state()

    # =====================================
    # REFRESH
    # =====================================

    def _on_refresh(self):
        """
        /**
         * Chức năng: Quét lại cổng COM và làm mới trạng thái ESP32 nếu đang
         *            kết nối (xử lý nút "Làm Mới").
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi load_ports() để cập nhật danh sách cổng.
         *   2. Nếu đang kết nối: gọi refresh_state() để yêu cầu kiểm tra lại SIM.
         */
        """
        self.load_ports()
        if state_manager.uart_connected:
            self.refresh_state()

    def refresh_state(self):
        """
        /**
         * Chức năng: Yêu cầu ESP32 kiểm tra lại đầy đủ trạng thái SIM và mạng
         *            (dùng CHECK_SYSTEM — chấp nhận chờ 5-10s).
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đặt waiting_system_response = True và cập nhật UI.
         *   2. Gọi uart_service.check_system() để gửi lệnh xuống ESP32.
         *   3. Khởi động timeout 15s.
         */
        """
        state_manager.waiting_system_response = True
        self.update_state()
        # check_system gọi checkSIMStatus trên ESP32 — dùng cho nút Làm Mới
        # (force re-check đầy đủ, chấp nhận chờ 5-10s)
        uart_service.check_system()
        self._state_timeout_timer.start(15000)

    # =====================================
    # UPDATE STATE
    # =====================================

    def update_state(self):
        """
        /**
         * Chức năng: Cập nhật toàn bộ giao diện StatusPage theo trạng thái
         *            hiện tại trong StateManager.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Nếu chưa kết nối: reset tất cả indicator về "---"/na và đổi nút.
         *   2. Nếu đang chờ SYSTEM_STATE: hiển thị "Đang kiểm tra..." cho các chỉ số SIM.
         *   3. Khi nhận được state: dừng timers, đồng bộ danh bạ lần đầu,
         *      cập nhật indicator MODULE SIM, THẺ SIM, MẠNG, SÓNG, CHẾ ĐỘ SMS.
         */
        """
        connected = state_manager.uart_connected

        if not connected:
            self._state_timeout_timer.stop()
            self._retry_timer.stop()
            self._contacts_synced = False
            self._set_indicator("ESP32",      "CHƯA KẾT NỐI", "na")
            for key in ["MODULE SIM", "THẺ SIM", "MẠNG", "SÓNG", "CHẾ ĐỘ SMS"]:
                self._set_indicator(key, "---", "na")
            self.connect_btn.setText("Kết Nối")
            self.connect_btn.setProperty("class", "success")
            self._refresh_btn_style(self.connect_btn)
            self.port_combo.setEnabled(True)
            return

        self._set_indicator("ESP32", "ĐÃ KẾT NỐI", "ok")
        self.connect_btn.setText("Ngắt Kết Nối")
        self.connect_btn.setProperty("class", "danger")
        self._refresh_btn_style(self.connect_btn)
        self.port_combo.setEnabled(False)

        if state_manager.waiting_system_response:
            for key in ["MODULE SIM", "THẺ SIM", "MẠNG", "SÓNG", "CHẾ ĐỘ SMS"]:
                self._set_indicator(key, "Đang kiểm tra...", "warn")
            return

        # Trạng thái thực nhận được — huỷ tất cả timeout timers
        self._state_timeout_timer.stop()
        self._retry_timer.stop()

        # Đồng bộ danh bạ ngay sau khi nhận SYSTEM_STATE lần đầu
        if not self._contacts_synced:
            self._contacts_synced = True
            uart_service.sync_all_contacts()

        self._set_indicator(
            "MODULE SIM",
            "SẴN SÀNG" if state_manager.sim_module else "LỖI",
            "ok"        if state_manager.sim_module else "error"
        )
        self._set_indicator(
            "THẺ SIM",
            "ĐÃ LẮP" if state_manager.sim_inserted else "KHÔNG CÓ",
            "ok"     if state_manager.sim_inserted else "error"
        )
        self._set_indicator(
            "MẠNG",
            "ĐÃ ĐĂNG KÝ" if state_manager.network_registered else "MẤT MẠNG",
            "ok"          if state_manager.network_registered else "error"
        )
        sig = state_manager.signal
        if sig == 0 or sig == 99:
            sig_text  = "Không xác định"
            sig_state = "na"
        elif sig >= 20:
            sig_text  = f"{sig}/31 — Tốt"
            sig_state = "ok"
        elif sig >= 10:
            sig_text  = f"{sig}/31 — Trung bình"
            sig_state = "warn"
        else:
            sig_text  = f"{sig}/31 — Yếu"
            sig_state = "error"
        self._set_indicator("SÓNG", sig_text, sig_state)
        self._set_indicator(
            "CHẾ ĐỘ SMS",
            "SẴN SÀNG" if state_manager.sms_ready else "LỖI",
            "ok"        if state_manager.sms_ready else "error"
        )

    # =====================================
    # HELPERS
    # =====================================

    def _set_indicator(self, key: str, text: str, state: str):
        """
        /**
         * Chức năng: Cập nhật dot indicator và label văn bản cho một chỉ số
         *            trạng thái trong STATUS CARD theo trạng thái ok/error/warn/na.
         * Tham số:
         *   - key   : tên chỉ số (khóa trong self.dots và self.labels)
         *   - text  : văn bản hiển thị trong label
         *   - state : "ok" | "error" | "warn" | "na"
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tra cứu ký tự dot và objectName theo state.
         *   2. Cập nhật dot và unpolish/polish để áp lại stylesheet màu.
         *   3. Cập nhật label text và objectName rồi unpolish/polish.
         */
        """
        dot_map  = {"ok": ("●", "dotOk"), "error": ("●", "dotError"),
                    "warn": ("●", "dotWarn"), "na": ("○", "dotNa")}
        text_map = {"ok": "statusOk", "error": "statusError",
                    "warn": "statusWarn", "na": "statusNa"}

        dot_char, dot_name = dot_map.get(state, ("○", "dotNa"))
        text_name          = text_map.get(state, "statusNa")

        dot = self.dots.get(key)
        lbl = self.labels.get(key)

        if dot:
            dot.setText(dot_char)
            dot.setObjectName(dot_name)
            dot.style().unpolish(dot)
            dot.style().polish(dot)

        if lbl:
            lbl.setText(text)
            lbl.setObjectName(text_name)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _refresh_btn_style(self, btn: QPushButton):
        """
        /**
         * Chức năng: Áp lại stylesheet cho nút sau khi thay đổi property
         *            (unpolish/polish để Qt tính lại màu sắc).
         * Tham số:
         *   - btn : QPushButton cần làm mới style
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi unpolish() rồi polish() trên btn.
         */
        """
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    # =====================================
    # STATE TIMEOUT
    # =====================================

    def _on_state_timeout(self):
        """
        /**
         * Chức năng: Xử lý khi hết thời gian chờ mà ESP32 chưa trả lời
         *            SYSTEM_STATE — hiển thị "Không phản hồi" cho các chỉ số.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Kiểm tra còn đang chờ phản hồi không.
         *   2. Đặt waiting_system_response = False và _contacts_synced = True.
         *   3. Gọi update_state() rồi set tất cả indicator SIM về "Không phản hồi".
         */
        """
        if state_manager.waiting_system_response:
            state_manager.waiting_system_response = False
            self._contacts_synced = True  # không sync khi timeout
            self.update_state()
            for key in ["MODULE SIM", "THẺ SIM", "MẠNG", "SÓNG", "CHẾ ĐỘ SMS"]:
                self._set_indicator(key, "Không phản hồi", "error")
