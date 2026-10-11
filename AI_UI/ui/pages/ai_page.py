import html as _html_mod
import re
import time
import threading
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from ai.recognition_worker import RecognitionWorker
from ai.manual_sms_mode import ManualSMSMode
from services.tts_service import tts_service
from core.event_bus import bus


# ─────────────────────────────────────────────────────────
# Tên tiếng Việt cho từng nhóm tình huống
# ─────────────────────────────────────────────────────────
CATEGORY_NAMES = {
    "kho_tho":            "Khó thở",
    "dau_tim":            "Đau tim",
    "dot_quy":            "Đột quỵ",
    "chay_no":            "Cháy / Nổ",
    "keu_cuu":            "Kêu cứu",
    "tre_bao_bat_thuong": "Trẻ báo bất thường",
    "co_giat":            "Co giật",
    "nguy_kich":          "Nguy kịch",
    "dien_giat":          "Điện giật",
    "nghen_tho":          "Nghẹn / Hóc",
    "nga_te":             "Ngã / Té",
    "chay_mau":           "Chảy máu",
    "bi_can":             "Bị cắn / Đốt",
    "bong":               "Bỏng",
    "gay_xuong":          "Gãy xương",
    "di_ung_nang":        "Dị ứng nặng",
    "ngo_doc":            "Ngộ độc",
    "tu_tu":              "Sức khoẻ tâm thần",
    "dau_nguoi_benh":     "Đau người",
    "met_moi":            "Mệt mỏi",
    "uong_thuoc":         "Uống thuốc",
    "sot":                "Sốt",
    "chong_mat":          "Chóng mặt",
    "buon_non":           "Buồn nôn",
    "mat_ngu":            "Mất ngủ",
    "ho":                 "Ho",
    "dau_khop":           "Đau khớp",
    "tre_bao_nguoi_benh": "Trẻ báo người bệnh",
    "can_ho_tro":         "Cần hỗ trợ",
    "tam_ly":             "Tâm lý",
    "khat_nuoc":          "Khát nước",
    "doi_bung":           "Đói bụng",
    "di_ve_sinh":         "Vệ sinh",
    "tro_minh":           "Trở mình",
    "muon_ngu":           "Muốn ngủ",
    "lanh_nong":          "Nhiệt độ",
    "tro_chuyen":         "Trò chuyện",
    "xem_tivi":           "Xem TV",
    "muon_choi":          "Muốn chơi",
    "goi_me":             "Gọi mẹ",
    "goi_ba":             "Gọi ba",
    "goi_ong":            "Gọi ông",
    "goi_ba_noi":         "Gọi bà",
    "nguoi_cham_soc":     "Gọi người chăm sóc",
    # Thêm mới
    "bi_xam_hai":         "Trẻ bị nguy hiểm",
    "huyet_ap":           "Huyết áp",
    "lac_duong":          "Lạc đường",
    "goi_con":            "Gọi con",
    "goi_hang_xom":       "Gọi hàng xóm",
}

# priority → (nhãn hiển thị, màu chữ, màu nền, màu viền trái)
PRIORITY_STYLE = {
    0: ("🚨 KHẨN CẤP",   "#c0392b", "#fff5f5", "#e74c3c"),
    1: ("🔴 NGUY HIỂM",  "#d35400", "#fff8f0", "#e67e22"),
    2: ("🟡 CẦN HỖ TRỢ", "#7d6608", "#fffdf0", "#f1c40f"),
    3: ("🟢 NHU CẦU",    "#1e8449", "#f0fff4", "#27ae60"),
}

_MAX_SPEECH_LINES = 500


def _he(text: str) -> str:
    """
    /**
     * Chức năng: Escape HTML đặc biệt trong text để hiển thị an toàn trong QTextEdit HTML.
     * Tham số:
     *   text : chuỗi cần escape
     * Trả về: str đã escape HTML
     */
    """
    return _html_mod.escape(str(text))


def _ts() -> str:
    """
    /**
     * Chức năng: Trả về timestamp hiện tại dạng HH:MM:SS để gắn vào dòng log.
     * Tham số: Không
     * Trả về: str "HH:MM:SS"
     */
    """
    return datetime.now().strftime("%H:%M:%S")


class AIPage(QWidget):

    # Signal dùng để update system_log từ background thread một cách an toàn.
    # QTextEdit.append() không thread-safe — phải đi qua signal/slot.
    _log_signal = pyqtSignal(str)

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo trang AI — cài đặt auto-restart, manual SMS mode,
         *            dựng UI, kết nối tất cả signal và bắt đầu nhận diện giọng nói.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Khởi tạo worker=None, bộ đếm restart, ManualSMSMode.
         *   2. Gọi setup_ui() và _load_history_from_db().
         *   3. Kết nối _log_signal, sms_result, manual_sms, new_sms, sms_delivery,
         *      sos_alert, stop_audio.
         *   4. Khởi động manual_timer (kiểm tra timeout mỗi 1s).
         *   5. Gọi start_recognition() để bắt đầu luồng ASR.
         */
        """
        super().__init__()

        self.worker = None
        self._speech_lines: list = []

        # ── Auto-restart tracking ──────────────────────────
        self._restart_count = 0
        self._MAX_RESTARTS  = 3
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._do_restart)

        self._manual_mode = ManualSMSMode()
        self._manual_mode.on_activate = self._on_manual_activated
        self._manual_mode.on_finalize = self._on_manual_finalized

        self._recent_sms: dict = {}  # (phone, message) → timestamp, chống nhận trùng

        self.setup_ui()
        self._log_signal.connect(self.system_log.append)
        self._load_history_from_db()

        bus.sms_result.connect(self.handle_sms_result, Qt.QueuedConnection)
        bus.manual_sms_started.connect(self._start_manual_sms, Qt.QueuedConnection)
        bus.manual_sms_stopped.connect(self._stop_manual_sms, Qt.QueuedConnection)
        bus.new_sms.connect(self.handle_new_sms, Qt.QueuedConnection)
        bus.sms_delivery.connect(self.handle_sms_delivery, Qt.QueuedConnection)
        bus.sos_alert.connect(self._handle_sos, Qt.QueuedConnection)
        bus.stop_audio.connect(self._handle_stop_audio, Qt.QueuedConnection)

        self._manual_timer = QTimer(self)
        self._manual_timer.setInterval(1000)
        self._manual_timer.timeout.connect(self._manual_mode.check_timeouts)
        self._manual_timer.start()

        self.start_recognition()

    # =====================================
    # PANEL 1 — VĂN BẢN NHẬN DIỆN
    # Giới hạn 50 dòng, có timestamp, tô màu khi khớp keyword
    # =====================================

    def _append_speech(self, text: str, state: str = "normal", priority: int = -1):
        """
        /**
         * Chức năng: Thêm dòng văn bản nhận diện vào panel 1 với màu sắc theo trạng thái
         *            và mức độ ưu tiên; giới hạn _MAX_SPEECH_LINES dòng.
         * Tham số:
         *   text     : văn bản ASR vừa nhận
         *   state    : "normal" | "match_sent" | "match_cooldown"
         *   priority : mức ưu tiên (0-3) dùng tra PRIORITY_STYLE
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo thẻ HTML span với màu nền/chữ theo state và priority.
         *   2. Thêm vào _speech_lines; xóa dòng cũ nhất nếu vượt giới hạn.
         *   3. Render lại toàn bộ HTML vào speech_text và cuộn xuống cuối.
         */
        """
        ts = _ts()
        escaped = _he(text)

        if state in ("match_sent", "match_cooldown"):
            _, tc, bg, _ = PRIORITY_STYLE.get(priority, ("", "#c0392b", "#fff5f5", ""))
            if state == "match_sent":
                line = (
                    f'<span style="background-color:{bg}; color:{tc}; '
                    f'font-weight:700; padding:1px 6px; border-radius:2px;">'
                    f'[{ts}] {escaped}</span>'
                )
            else:
                # Italic + ⏳ để phân biệt cooldown với match_sent cùng màu priority
                line = (
                    f'<span style="background-color:{bg}; color:{tc}; '
                    f'font-weight:600; font-style:italic; padding:1px 6px; border-radius:2px;">'
                    f'[{ts}] {escaped} ⏳</span>'
                )
        else:
            line = f'<span style="color:#5d6d7e;">[{ts}] {escaped}</span>'

        self._speech_lines.append(line)
        if len(self._speech_lines) > _MAX_SPEECH_LINES:
            self._speech_lines.pop(0)

        body = "".join(f"<div>{l}</div>" for l in self._speech_lines)
        self.speech_text.setHtml(
            f"<div style='font-size:15px; line-height:1.7;'>{body}</div>"
        )
        sb = self.speech_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # =====================================
    # PANEL 2 — SỰ KIỆN & CẢNH BÁO
    # Thẻ HTML mỗi sự kiện, tên tiếng Việt, trạng thái SMS
    # =====================================

    def _append_event(self, priority: int, category: str, keyword: str,
                      text: str, sms_sent: bool, reason: str):
        """
        /**
         * Chức năng: Thêm thẻ HTML sự kiện vào panel 2 với màu viền trái theo mức ưu tiên,
         *            tên danh mục tiếng Việt và trạng thái gửi SMS.
         * Tham số:
         *   priority : mức ưu tiên (0-3)
         *   category : key danh mục (tra CATEGORY_NAMES)
         *   keyword  : từ khóa kích hoạt
         *   text     : văn bản gốc vừa nhận
         *   sms_sent : True nếu SMS đã được gửi
         *   reason   : lý do không gửi SMS (nếu sms_sent=False)
         * Trả về: None
         */
        """
        ts = _ts()
        label, tc, bg, bc = PRIORITY_STYLE.get(priority, ("?", "#555", "#fff", "#ccc"))
        cat_name = CATEGORY_NAMES.get(category, category)

        if sms_sent:
            sms_row = (
                f'<div style="margin-top:5px; color:#1a5276; font-size:14px;">'
                f'📤 SMS đã kích hoạt gửi</div>'
            )
        elif reason == "COOLDOWN_OR_SMS_FAILED":
            sms_row = (
                f'<div style="margin-top:5px; color:#7d6608; font-size:14px;">'
                f'⏳ SMS trong cooldown — bỏ qua lần này</div>'
            )
        else:
            sms_row = (
                f'<div style="margin-top:5px; color:#7f8c8d; font-size:14px;">'
                f'ℹ {_he(reason)}</div>'
            )

        card = (
            f'<div style="background:{bg}; border-left:4px solid {bc}; '
            f'margin:4px 2px; padding:8px 10px; border-radius:4px;">'
            f'<span style="color:#7f8c8d; font-size:13px;">[{ts}]</span> '
            f'<span style="color:{tc}; font-weight:700; font-size:15px;">'
            f'{_he(label)}</span>'
            f'<span style="color:#555; font-size:14px;"> | {_he(cat_name)}</span>'
            f'<div style="color:#666; font-size:14px; margin-top:4px; padding-left:4px;">'
            f'Từ khóa: <i>{_he(keyword)}</i></div>'
            f'<div style="color:#333; font-size:14px; padding-left:4px;">'
            f'"{_he(text)}"</div>'
            f'{sms_row}'
            f'</div>'
        )
        self.event_text.append(card)
        sb = self.event_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append_event_warning(self, text: str):
        """
        /**
         * Chức năng: Thêm thẻ cảnh báo màu vàng vào panel 2 — dùng cho lỗi ASR
         *            hoặc các cảnh báo hệ thống quan trọng.
         * Tham số:
         *   text : nội dung cảnh báo
         * Trả về: None
         */
        """
        ts = _ts()
        card = (
            f'<div style="background:#fef9e7; border-left:4px solid #f39c12; '
            f'margin:4px 2px; padding:8px 10px; border-radius:4px;">'
            f'<span style="color:#7f8c8d; font-size:13px;">[{ts}]</span> '
            f'<span style="color:#d35400; font-weight:700; font-size:15px;">'
            f'⚠ CẢNH BÁO HỆ THỐNG</span>'
            f'<div style="color:#555; font-size:14px; margin-top:4px;">'
            f'{_he(text)}</div>'
            f'</div>'
        )
        self.event_text.append(card)
        sb = self.event_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # =====================================
    # PANEL 4 — TIN NHẮN QUA LẠI
    # SMS đến, gửi thành công, delivery report
    # =====================================

    def _append_message(self, icon: str, label: str, body: str,
                        color: str = "#2c3e50"):
        """
        /**
         * Chức năng: Thêm một mục tin nhắn vào panel 4 (SMS đến/đi, delivery report)
         *            dưới dạng HTML với icon, nhãn màu và nội dung.
         * Tham số:
         *   icon  : emoji biểu tượng (vd "✅", "📨")
         *   label : nhãn hiển thị (tên người gửi/nhận)
         *   body  : nội dung tin nhắn
         *   color : màu chữ nhãn (mặc định "#2c3e50")
         * Trả về: None
         */
        """
        ts = _ts()
        html = (
            f'<div style="padding:6px 4px; border-bottom:1px solid #f0f4f8;">'
            f'<span style="color:#7f8c8d; font-size:13px;">[{ts}]</span> '
            f'{icon} <span style="color:{color}; font-weight:600;">'
            f'{_he(label)}</span>'
            f'<div style="color:#555; font-size:14px; '
            f'padding-left:18px; margin-top:2px;">{_he(body)}</div>'
            f'</div>'
        )
        self.message_text.append(html)
        sb = self.message_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # =====================================
    # SMS RESULT
    # =====================================

    def handle_sms_result(self, payload):
        """
        /**
         * Chức năng: Xử lý kết quả gửi SMS từ ESP32 — cập nhật log, panel 4
         *            và khởi động luồng retry nếu thất bại.
         * Tham số:
         *   payload : dict {"packet_id", "phone", "status"} từ signal sms_result
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tra _sms_pending để lấy message gốc.
         *   2. Nếu SUCCESS: xóa khỏi pending, log thành công.
         *   3. Nếu FAILED: log thất bại, spawn thread _retry_sms.
         */
        """
        from services.database_service import database_service
        from ai.keyword_engine import _sms_pending

        packet_id = payload.get("packet_id", "")
        phone     = payload.get("phone",     "")
        status    = payload.get("status",    "")

        entry   = _sms_pending.get(packet_id)
        message = entry["packet"].get("payload", {}).get("message", "") if entry else ""

        contact = database_service.get_contact_by_phone(phone)
        label   = f"{contact[0]} ({phone})" if contact else phone

        if status == "SUCCESS":
            _sms_pending.pop(packet_id, None)
            database_service.add_log(f'[SMS ĐI] Thành công | {label}: "{message}"')
            self._append_message("✅", f"Đã gửi: {label}", message, "#1a5276")
        else:
            database_service.add_log(f'[SMS ĐI] Thất bại | {label}: "{message}"')
            self._append_message("❌", f"Gửi thất bại: {label}",
                                 "Đang thử lại...", "#c0392b")
            threading.Thread(
                target=self._retry_sms, args=(packet_id,), daemon=True
            ).start()

    def _retry_sms(self, packet_id: str):
        """
        /**
         * Chức năng: Thử lại gửi SMS tối đa 2 lần với delay 30 giây; hủy nếu liên hệ
         *            bị xóa trong lúc chờ hoặc đã đủ số lần thử.
         * Tham số:
         *   packet_id : ID packet gốc trong _sms_pending cần retry
         * Trả về: None
         * Luồng hoạt động:
         *   1. Kiểm tra entry còn tồn tại và retry_count < 2.
         *   2. Sleep 30s; kiểm tra lại liên hệ còn trong DB không.
         *   3. Tạo packet mới với ID "R{n}_{suffix}", xóa packet cũ, gửi lại.
         *   4. Nếu hết retry: log thất bại hoàn toàn, dùng _log_signal (thread-safe).
         */
        """
        from ai.keyword_engine import _sms_pending
        from services.uart_service import uart_service

        entry = _sms_pending.get(packet_id)
        if entry is None:
            return

        phone = entry["packet"].get("payload", {}).get("phone", "")

        if entry["retry_count"] >= 2:
            _sms_pending.pop(packet_id, None)
            from services.database_service import database_service
            database_service.add_log(
                f"[SMS ĐI] Thất bại hoàn toàn sau 2 lần thử lại | {phone} | {packet_id}"
            )
            # _append_message() không thread-safe từ background thread —
            # dùng _log_signal để queue sang main thread
            self._log_signal.emit(f"[SMS] {packet_id}: thất bại hoàn toàn sau 2 lần thử")
            return

        time.sleep(30)

        # Lớp bảo vệ thứ hai: liên hệ bị xóa trong lúc chờ retry → hủy
        if phone:
            from services.database_service import database_service
            if not database_service.get_contact_by_phone(phone):
                _sms_pending.pop(packet_id, None)
                self._log_signal.emit(f"[SMS] {packet_id}: liên hệ đã bị xóa — hủy retry")
                return

        entry["retry_count"] += 1
        old_pkt = entry["packet"]
        new_id  = f"R{entry['retry_count']}_{packet_id[-10:]}"

        new_pkt = dict(old_pkt)
        new_pkt["packet_id"] = new_id
        new_pkt["timestamp"] = int(time.time())

        _sms_pending[new_id] = {"packet": new_pkt, "retry_count": entry["retry_count"]}
        _sms_pending.pop(packet_id, None)

        uart_service.send_packet(new_pkt)
        self._log_signal.emit(f"[SMS] Retry lần {entry['retry_count']}: {new_id}")

    # =====================================
    # WORKER CONTROL
    # =====================================

    def start_recognition(self):
        """
        /**
         * Chức năng: Tạo và khởi động RecognitionWorker nếu chưa có; kết nối các signal
         *            log/result/error/status và cập nhật trạng thái nút mic.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Nếu worker đang tồn tại → return ngay.
         *   2. Đặt mic_muted=False, tạo RecognitionWorker, kết nối signal.
         *   3. Gọi worker.start() và bật nút mic màu xanh.
         */
        """
        if self.worker is not None:
            return
        from core.state_manager import state_manager
        state_manager.mic_muted = False
        self.worker = RecognitionWorker()
        self.worker.log_signal.connect(self.on_log)
        self.worker.result_signal.connect(self.on_result)
        self.worker.error_signal.connect(self.on_error)
        self.worker.status_signal.connect(self.on_status)
        self.worker.start()
        self._mic_btn.setEnabled(True)
        self._mic_btn.setText("🎙 Tắt Mic")
        self._mic_btn.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; border:none; "
            "border-radius:4px; padding:0 10px; font-size:13px; font-weight:600; }"
            "QPushButton:hover { background:#1e8449; }"
        )

    def stop_recognition(self):
        """
        /**
         * Chức năng: Dừng worker ASR — hủy timer restart, gọi worker.stop() và
         *            wait(5s) rồi giải phóng; cập nhật trạng thái nút mic.
         * Tham số: Không
         * Trả về: None
         */
        """
        self._restart_timer.stop()   # hủy restart đang chờ (nếu có)
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(5000)
            self.worker = None
        self._mic_btn.setEnabled(False)
        self._mic_btn.setText("🎙 Tắt Mic")
        self._mic_btn.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; border:none; "
            "border-radius:4px; padding:0 10px; font-size:13px; font-weight:600; }"
            "QPushButton:hover { background:#1e8449; }"
        )

    def _toggle_mic(self):
        """
        /**
         * Chức năng: Bật/tắt microphone bằng cách đảo state_manager.mic_muted;
         *            cập nhật màu nút và ghi log.
         * Tham số: Không
         * Trả về: None
         */
        """
        from core.state_manager import state_manager
        if state_manager.mic_muted:
            # Bật lại mic
            state_manager.mic_muted = False
            self._mic_btn.setText("🎙 Tắt Mic")
            self._mic_btn.setStyleSheet(
                "QPushButton { background:#27ae60; color:white; border:none; "
                "border-radius:4px; padding:0 10px; font-size:13px; font-weight:600; }"
                "QPushButton:hover { background:#1e8449; }"
            )
            self.system_log.append("[MIC] Microphone đã BẬT")
        else:
            # Tắt mic
            state_manager.mic_muted = True
            self._mic_btn.setText("🔇 Bật Mic")
            self._mic_btn.setStyleSheet(
                "QPushButton { background:#c0392b; color:white; border:none; "
                "border-radius:4px; padding:0 10px; font-size:13px; font-weight:600; }"
                "QPushButton:hover { background:#922b21; }"
            )
            self.system_log.append("[MIC] Microphone đã TẮT")

    # =====================================
    # AUTO-RESTART
    # =====================================

    def _schedule_restart(self):
        """
        /**
         * Chức năng: Lên lịch khởi động lại worker sau 5 giây, tối đa _MAX_RESTARTS lần.
         *            Nếu vượt giới hạn thì hiện cảnh báo và tô đỏ ASR dot.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Nếu _restart_count >= _MAX_RESTARTS: log cảnh báo, tô đỏ dot, return.
         *   2. Tăng bộ đếm, tô vàng dot, khởi động _restart_timer 5000ms.
         */
        """
        if self._restart_count >= self._MAX_RESTARTS:
            self.system_log.append(
                f"[AUTO-RESTART] Đã thử {self._MAX_RESTARTS} lần — "
                "yêu cầu kiểm tra microphone và khởi động lại ứng dụng"
            )
            self._append_event_warning(
                f"Hệ thống nhận diện gặp lỗi {self._MAX_RESTARTS} lần liên tiếp.\n"
                "Vui lòng kiểm tra microphone và khởi động lại ứng dụng."
            )
            from services.database_service import database_service
            database_service.add_log(
                f"[CẢNH BÁO] ASR lỗi {self._MAX_RESTARTS} lần liên tiếp — "
                "cần kiểm tra microphone và khởi động lại ứng dụng"
            )
            self._asr_dot.setStyleSheet(
                "color:#e74c3c; font-size:14px; background:transparent;"
            )
            self._asr_dot.setToolTip("ASR lỗi nghiêm trọng — cần khởi động lại ứng dụng")
            return

        self._restart_count += 1
        self.system_log.append(
            f"[AUTO-RESTART] Lần {self._restart_count}/{self._MAX_RESTARTS} "
            "— khởi động lại sau 5 giây..."
        )
        self._asr_dot.setStyleSheet(
            "color:#f39c12; font-size:14px; background:transparent;"
        )
        self._asr_dot.setToolTip(
            f"ASR đang khởi động lại ({self._restart_count}/{self._MAX_RESTARTS})..."
        )
        self._restart_timer.start(5000)

    def _do_restart(self):
        """
        /**
         * Chức năng: Được gọi bởi _restart_timer sau 5 giây — dọn worker cũ và tạo mới.
         * Tham số: Không
         * Trả về: None
         */
        """
        self.system_log.append("[AUTO-RESTART] Đang khởi động lại worker...")

        if self.worker is not None:
            try:
                self.worker.stop()
                self.worker.wait(3000)
            except Exception:
                pass
            self.worker = None

        self.start_recognition()

    # =====================================
    # SIGNAL HANDLERS
    # =====================================

    def on_log(self, msg):
        """
        /**
         * Chức năng: Nhận log text từ RecognitionWorker và thêm vào system_log panel.
         * Tham số:
         *   msg : chuỗi log từ worker
         * Trả về: None
         */
        """
        self.system_log.append(msg)

    def on_error(self, msg):
        """
        /**
         * Chức năng: Nhận lỗi từ worker — log dòng đầu tiên (tránh flooding traceback)
         *            và lên lịch auto-restart.
         * Tham số:
         *   msg : chuỗi lỗi (có thể nhiều dòng)
         * Trả về: None
         */
        """
        # Chỉ log dòng đầu tiên để tránh flooding nhật ký với traceback dài
        first_line = msg.splitlines()[0] if msg else "Lỗi không xác định"
        self.system_log.append(f"[LỖI] {first_line}")
        self._schedule_restart()

    def on_status(self, status):
        """
        /**
         * Chức năng: Cập nhật trạng thái ASR dot và system_log theo trạng thái
         *            "ASR_OFFLINE", "RUNNING" hoặc chuỗi khác.
         * Tham số:
         *   status : chuỗi trạng thái từ worker
         * Trả về: None
         * Luồng hoạt động:
         *   1. ASR_OFFLINE: tô đỏ dot, log DB cảnh báo, hiện event warning.
         *   2. RUNNING: tô xanh dot, reset bộ đếm restart.
         *   3. Khác: log thô vào system_log.
         */
        """
        if status == "ASR_OFFLINE":
            from services.database_service import database_service
            database_service.add_log(
                "[CẢNH BÁO] ASR gặp lỗi liên tiếp — cần kiểm tra microphone"
            )
            self._asr_dot.setStyleSheet(
                "color:#e74c3c; font-size:14px; background:transparent;"
            )
            self._asr_dot.setToolTip("ASR lỗi — kiểm tra microphone")
            self.system_log.append(
                "[CẢNH BÁO] ASR GẶP LỖI LIÊN TIẾP — Kiểm tra microphone hoặc khởi động lại"
            )
            self._append_event_warning(
                "ASR GẶP LỖI — Nhận diện giọng nói có thể bị gián đoạn"
            )
        elif status == "RUNNING":
            self._asr_dot.setStyleSheet(
                "color:#27ae60; font-size:14px; background:transparent;"
            )
            self._asr_dot.setToolTip("ASR đang hoạt động")
            self.system_log.append("[TRẠNG THÁI] ASR đang hoạt động")
            self._restart_count = 0   # khởi động thành công → reset bộ đếm
        else:
            self.system_log.append(f"[TRẠNG THÁI] {status}")

    def on_result(self, event):
        """
        /**
         * Chức năng: Xử lý kết quả nhận diện từ worker — phân luồng manual SMS mode
         *            hoặc hiển thị speech + event và ghi log DB nếu keyword khớp.
         * Tham số:
         *   event : dict {"text", "matched", "sms_sent", "priority",
         *                 "category", "keyword", "reason"}
         * Trả về: None
         * Luồng hoạt động:
         *   1. Nếu manual mode đang hoạt động: chuyển text sang ManualSMSMode.
         *   2. Nếu matched: gọi _append_speech với state màu, _append_event, log DB.
         *   3. Nếu không khớp: _append_speech dạng normal.
         */
        """
        text = event["text"]

        if self._manual_mode.is_active():
            self._manual_mode.add_text(text)
            self.system_log.append(f"[MANUAL SMS] Thu: {text}")
            self._append_speech(text, state="normal")
            return

        if event["matched"]:
            state = "match_sent" if event["sms_sent"] else "match_cooldown"
            self._append_speech(text, state=state, priority=event["priority"])
            self._append_event(
                event["priority"], event["category"], event["keyword"],
                text, event["sms_sent"], event["reason"],
            )
            from services.database_service import database_service
            _p_labels = {0: "🚨 KHẨN CẤP", 1: "🔴 NGUY HIỂM",
                         2: "🟡 CẦN HỖ TRỢ", 3: "🟢 NHU CẦU"}
            _p_label  = _p_labels.get(event["priority"], f'P{event["priority"]}')
            _cat_name = CATEGORY_NAMES.get(event["category"], event["category"])
            _sms_st   = "SMS đã gửi" if event["sms_sent"] else "SMS cooldown"
            database_service.add_log(
                f'[SỰ KIỆN] {_p_label} | {_cat_name} | '
                f'Từ khóa: "{event["keyword"]}" | "{event["text"]}" | {_sms_st}'
            )
        else:
            self._append_speech(text, state="normal")

    # =====================================
    # MANUAL SMS MODE
    # =====================================

    def _start_manual_sms(self):
        """
        /**
         * Chức năng: Kích hoạt ManualSMSMode khi nhận signal manual_sms_started từ bus.
         * Tham số: Không
         * Trả về: None
         */
        """
        self._manual_mode.activate()

    def _stop_manual_sms(self):
        """
        /**
         * Chức năng: Dừng ManualSMSMode khi nhận signal manual_sms_stopped từ bus.
         * Tham số: Không
         * Trả về: None
         */
        """
        self._manual_mode.stop()

    def _on_manual_activated(self):
        """
        /**
         * Chức năng: Callback khi ManualSMSMode bắt đầu — tạm dừng keyword engine
         *            và phát hướng dẫn bằng TTS.
         * Tham số: Không
         * Trả về: None
         */
        """
        if self.worker and self.worker.engine:
            self.worker.engine.pause()
        self.system_log.append("[MANUAL SMS] Chế độ ghi âm thủ công ĐÃ BẬT")
        tts_service.speak(
            "Xin hãy nói nội dung tin nhắn. "
            "Nhấn nút màu xanh để gửi ngay. "
            "Nếu quên, hệ thống sẽ tự gửi."
        )

    def _on_manual_finalized(self, text: str, reason: str):
        """
        /**
         * Chức năng: Callback khi ManualSMSMode kết thúc — resume keyword engine,
         *            gửi nội dung text hoặc cảnh báo nếu không có nội dung.
         * Tham số:
         *   text   : nội dung giọng nói tổng hợp (có thể rỗng)
         *   reason : "manual_stop" | "timeout_no_text" | "timeout_max_duration"
         * Trả về: None
         * Luồng hoạt động:
         *   1. Resume keyword engine.
         *   2. Nếu có text: spawn thread _send_manual_sms_thread(text).
         *   3. Nếu rỗng và can_send_empty_warning(): spawn thread gửi cảnh báo.
         */
        """
        if self.worker and self.worker.engine:
            self.worker.engine.resume()

        reason_display = {
            "manual_stop":          "nhấn nút màu xanh",
            "timeout_no_text":      "timeout 15s không có giọng nói",
            "timeout_max_duration": "timeout tối đa 60s",
        }.get(reason, reason)

        self.system_log.append(f"[MANUAL SMS] Kết thúc ({reason_display})")

        if text:
            self._append_message("🎙", "Manual SMS", f'"{text}"', "#1a5276")
            threading.Thread(
                target=self._send_manual_sms_thread, args=(text,), daemon=True
            ).start()
        else:
            if self._manual_mode.can_send_empty_warning():
                warning = (
                    "Người dùng đã kích hoạt chức năng gửi tin nhắn "
                    "bằng giọng nói nhưng hệ thống không nhận được nội dung."
                )
                self.system_log.append("[MANUAL SMS] Không có nội dung — gửi cảnh báo")
                threading.Thread(
                    target=self._send_manual_sms_thread, args=(warning,), daemon=True
                ).start()
            else:
                self.system_log.append(
                    "[MANUAL SMS] Không có nội dung — anti-spam chặn"
                )

    def _send_manual_sms_thread(self, message: str):
        """
        /**
         * Chức năng: Gửi tin nhắn thủ công tới tất cả liên hệ có vai trò "NHẬN TIN NHẮN"
         *            với delay 3s giữa mỗi số; chạy trong background thread.
         * Tham số:
         *   message : nội dung tin nhắn cần gửi
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy danh sách phone theo role "NHẬN TIN NHẮN"; return nếu rỗng.
         *   2. Build packet SEND_MANUAL_SMS, thêm vào _sms_pending, gửi qua UART.
         *   3. Sleep 3s giữa mỗi số; log kết quả và phát TTS xác nhận.
         */
        """
        from services.database_service import database_service
        from services.uart_service import uart_service

        phones = database_service.get_phones_by_role("NHẬN TIN NHẮN")
        if not phones:
            self._log_signal.emit("[MANUAL SMS] Không tìm thấy số liên hệ")
            return

        from ai.keyword_engine import _sms_pending
        for phone in phones:
            packet = {
                "type":      "COMMAND",
                "command":   "SEND_MANUAL_SMS",
                "packet_id": f"MSMS_{int(time.time() * 1000)}",
                "source":    "AI_UI",
                "target":    "ESP32",
                "timestamp": int(time.time()),
                "payload": {
                    "phone":    phone,
                    "priority": 1,
                    "category": "MANUAL",
                    "message":  message,
                },
            }
            _sms_pending[packet["packet_id"]] = {"packet": packet, "retry_count": 0}
            uart_service.send_packet(packet)
            time.sleep(3)

        database_service.add_log(
            f'[MANUAL SMS] Nội dung: "{message}" — gửi tới {len(phones)} số'
        )
        self._log_signal.emit(f"[MANUAL SMS] Đã gửi tới {len(phones)} số")
        tts_service.speak("Tin nhắn đã được gửi.")

    # =====================================
    # AUDIO STOP HANDLER
    # =====================================

    def _handle_stop_audio(self):
        """
        /**
         * Chức năng: Dừng TTS đang phát khi nhận signal stop_audio (phím A trên keypad).
         * Tham số: Không
         * Trả về: None
         */
        """
        if tts_service.is_playing():
            tts_service.stop()
            self.system_log.append("[TTS] Dừng phát âm thanh theo yêu cầu phím A")
        else:
            self.system_log.append("[TTS] Phím A — không có âm thanh đang phát")

    # =====================================
    # SOS HANDLER
    # =====================================

    def _append_sos_card(self, body: str):
        """
        /**
         * Chức năng: Thêm thẻ SOS màu đỏ đậm vào panel 2 — dùng khi người dùng
         *            nhấn nút SOS vật lý trên ESP32.
         * Tham số:
         *   body : nội dung mô tả sự kiện SOS
         * Trả về: None
         */
        """
        ts = _ts()
        card = (
            f'<div style="background:#fff0f0; border-left:6px solid #c0392b; '
            f'margin:4px 2px; padding:10px 12px; border-radius:4px;">'
            f'<span style="color:#7f8c8d; font-size:13px;">[{ts}]</span> '
            f'<span style="color:#c0392b; font-weight:800; font-size:16px;">'
            f'🚨 SOS — KHẨN CẤP</span>'
            f'<div style="color:#333; font-size:14px; margin-top:6px;">'
            f'{_he(body)}</div>'
            f'</div>'
        )
        self.event_text.append(card)
        sb = self.event_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _handle_sos(self):
        """
        /**
         * Chức năng: Xử lý signal sos_alert từ bus — log DB, hiển thị SOS card,
         *            phát TTS cảnh báo và spawn thread gửi SMS đến tất cả liên hệ.
         * Tham số: Không
         * Trả về: None
         */
        """
        from services.database_service import database_service
        database_service.add_log("[SOS] Người dùng nhấn nút SOS khẩn cấp")
        self.system_log.append("[SOS] Nhận tín hiệu khẩn cấp từ ESP32")
        self._append_sos_card("Nút SOS đã được nhấn — đang gửi cảnh báo đến tất cả liên hệ...")
        tts_service.speak("Cảnh báo khẩn cấp! Đang gửi tin nhắn đến tất cả người thân.")
        threading.Thread(target=self._send_sos_sms_thread, daemon=True).start()

    def _send_sos_sms_thread(self):
        """
        /**
         * Chức năng: Gửi SMS khẩn cấp SOS tới tất cả liên hệ trong danh bạ;
         *            chạy trong background thread với delay 3s giữa mỗi số.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy toàn bộ phone từ database_service.get_all_phones().
         *   2. Build packet SEND_SMS với category="SOS", priority=0.
         *   3. Lưu vào _sms_pending, gửi qua UART, delay 3s.
         *   4. Log DB và phát TTS xác nhận hoàn tất.
         */
        """
        from services.database_service import database_service
        from services.uart_service import uart_service
        from ai.keyword_engine import _sms_pending
        from datetime import datetime

        phones = database_service.get_all_phones()
        if not phones:
            self._log_signal.emit("[SOS] Không có liên hệ nào trong danh bạ")
            return

        now_str = datetime.now().strftime("%H:%M")
        message = f"[SOS]{now_str}: Người dùng nhấn nút khẩn cấp - Cần hỗ trợ ngay!"

        for phone in phones:
            packet = {
                "type":      "COMMAND",
                "command":   "SEND_SMS",
                "packet_id": f"SOS_{int(time.time() * 1000)}",
                "source":    "AI_UI",
                "target":    "ESP32",
                "timestamp": int(time.time()),
                "payload": {
                    "phone":    phone,
                    "priority": 0,
                    "category": "SOS",
                    "message":  message,
                },
            }
            _sms_pending[packet["packet_id"]] = {"packet": packet, "retry_count": 0}
            uart_service.send_packet(packet)
            time.sleep(3)

        database_service.add_log(
            f"[SOS] Gửi cảnh báo khẩn cấp đến {len(phones)} liên hệ lúc {now_str}"
        )
        self._log_signal.emit(f"[SOS] Hoàn tất — đã gửi tới {len(phones)} số")
        tts_service.speak("Tin nhắn khẩn cấp đã được gửi.")

    # =====================================
    # SMS DELIVERY REPORT
    # =====================================

    def handle_sms_delivery(self, payload: dict):
        """
        /**
         * Chức năng: Hiển thị trạng thái delivery report (DELIVERED/thất bại) vào
         *            panel 4 và ghi log DB.
         * Tham số:
         *   payload : dict {"phone", "status"} từ signal sms_delivery
         * Trả về: None
         */
        """
        from services.database_service import database_service

        phone  = payload.get("phone",  "")
        status = payload.get("status", "")

        contact = database_service.get_contact_by_phone(phone)
        label   = f"{contact[0]} ({phone})" if contact else (phone or "?")

        if status == "DELIVERED":
            database_service.add_log(f'[DELIVERY] Đã nhận | {label}')
            self._append_message(
                "📬", f"Đã nhận: {label}",
                "Tin nhắn đã tới tay người nhận", "#1a5276"
            )
        else:
            database_service.add_log(f'[DELIVERY] Thất bại | {label}')
            self._append_message(
                "📵", f"Không giao được: {label}",
                "Tin nhắn chưa tới tay người nhận", "#c0392b"
            )

    # =====================================
    # NEW SMS (TIN NHẮN TỪ NGƯỜI THÂN)
    # =====================================

    @staticmethod
    def _is_real_phone(phone: str, contact) -> bool:
        """
        /**
         * Chức năng: Kiểm tra SMS có từ người thật hay short code nhà mạng.
         *   - Có trong danh bạ → luôn tin tưởng
         *   - Số VN hợp lệ: 10 chữ số bắt đầu 0 hoặc +84 + 9 chữ số
         *   - Ngoài ra (short code, chứa chữ cái, ...) → nhà mạng/quảng cáo
         * Tham số:
         *   phone   : số điện thoại người gửi
         *   contact : kết quả get_contact_by_phone (None nếu không có trong DB)
         * Trả về: bool — True nếu là số thật cần xử lý
         */
        """
        if contact:
            return True
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10 and digits.startswith("0"):
            return True
        if phone.startswith("+84") and len(digits) == 11:
            return True
        return False

    def handle_new_sms(self, payload: dict):
        """
        /**
         * Chức năng: Xử lý SMS mới đến từ ESP32 — lọc trùng lặp, lọc short code,
         *            phân luồng Quick Message hoặc SMS thông thường rồi phát TTS.
         * Tham số:
         *   payload : dict {"phone", "message"} từ signal new_sms
         * Trả về: None
         * Luồng hoạt động:
         *   1. Chống trùng: cùng (phone, message) trong 60s → bỏ qua.
         *   2. Lọc short code nhà mạng qua _is_real_phone().
         *   3. Nếu message là số 1-10: tra Quick Message, phát TTS và emit signal.
         *   4. Nếu là SMS thông thường: log, hiện panel 4, phát TTS speak_sms().
         */
        """
        from services.database_service import database_service

        phone   = payload.get("phone",   "")
        message = payload.get("message", "")

        if not message:
            return

        # Chống nhận trùng: cùng (phone, message) trong vòng 60s → bỏ qua
        _key = (phone, message)
        _now = time.time()
        if _key in self._recent_sms and _now - self._recent_sms[_key] < 60.0:
            self.system_log.append(f"[SMS] Bỏ qua trùng lặp từ {phone}")
            return
        self._recent_sms[_key] = _now
        self._recent_sms = {k: v for k, v in self._recent_sms.items() if _now - v < 60.0}

        contact = database_service.get_contact_by_phone(phone)
        if contact:
            name, relation = contact
            sender_label = f"{name} — {relation} ({phone})"
        else:
            sender_label = phone

        # ── LỌC SHORT CODE NHÀ MẠNG ─────────────────────────────
        # SMS từ 211, 9778, ... chỉ hiện log, KHÔNG phát âm thanh.
        if not self._is_real_phone(phone, contact):
            self.system_log.append(
                f"[SMS] Bỏ qua tin nhắn từ {phone} (nhà mạng/quảng cáo)"
            )
            return

        # ── QUICK MESSAGE: nội dung là số nguyên 1-10 ───────────
        msg_stripped = message.strip()
        if msg_stripped.isdigit():
            slot = int(msg_stripped)
            if 1 <= slot <= 10:
                quick_text = database_service.get_quick_message(slot)
                if quick_text:
                    database_service.add_log(
                        f'[TIN NHANH] Slot #{slot} từ {sender_label}: "{quick_text}"'
                    )
                    self._append_message(
                        "🔔",
                        f"Tin nhanh #{slot} từ {sender_label}",
                        quick_text,
                        "#8e44ad",
                    )
                    tts_service.speak_sms(quick_text)
                    bus.quick_message_triggered.emit(slot, sender_label, quick_text)
                    return
                else:
                    # Slot tồn tại nhưng chưa được cài đặt nội dung
                    database_service.add_log(
                        f'[TIN NHANH] Slot #{slot} từ {sender_label}: chưa có nội dung'
                    )
                    self._append_message(
                        "⚠",
                        f"Tin nhanh #{slot} từ {sender_label}",
                        f"Slot #{slot} chưa được cài đặt nội dung (vào trang Tin Nhắn Nhanh để cài)",
                        "#e67e22",
                    )
                    return

        # ── SMS THÔNG THƯỜNG ─────────────────────────────────────
        if contact:
            name, relation = contact
            tts_text = f"{relation} nói là: {message}"
        else:
            tts_text = f"Có tin nhắn từ số {phone}. Nội dung: {message}"

        database_service.add_log(f'[SMS ĐẾN] {sender_label}: "{message}"')
        self._append_message("📨", f"Tin đến: {sender_label}", message, "#1a5276")
        tts_service.speak_sms(tts_text)

    # =====================================
    # CLOSE EVENT
    # =====================================

    def closeEvent(self, event):
        """
        /**
         * Chức năng: Dừng worker ASR khi cửa sổ đóng để giải phóng tài nguyên.
         * Tham số:
         *   event : QCloseEvent
         * Trả về: None
         */
        """
        self.stop_recognition()
        super().closeEvent(event)

    # =====================================
    # UI
    # =====================================
    # LOAD HISTORY FROM DB ON STARTUP
    # =====================================

    def _load_history_from_db(self):
        """
        /**
         * Chức năng: Tải 100 dòng nhật ký gần nhất từ DB và hiển thị vào system_log
         *            khi khởi động ứng dụng để người dùng thấy lịch sử phiên trước.
         * Tham số: Không
         * Trả về: None
         */
        """
        from services.database_service import database_service
        rows = database_service.load_logs()
        if not rows:
            return
        recent = list(reversed(rows[:100]))
        self.system_log.append("─── Nhật ký phiên trước ───")
        for ts, msg in recent:
            self.system_log.append(f"[{ts[:16]}] {msg}")
        self.system_log.append("─── Phiên hiện tại ───")

    # =====================================

    def setup_ui(self):
        """
        /**
         * Chức năng: Dựng toàn bộ giao diện 4 panel — VĂN BẢN (panel 1), SỰ KIỆN (panel 2),
         *            NHẬT KÝ (panel 3), TIN NHẮN (panel 4) theo layout 2×2.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo header với tiêu đề và mô tả trang.
         *   2. Top row (5 phần): panel VĂN BẢN + nút mic + ASR dot; panel SỰ KIỆN.
         *   3. Bottom row (3 phần): panel NHẬT KÝ (monospace); panel TIN NHẮN.
         */
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # ─────────────────────────────────
        # PAGE HEADER
        # ─────────────────────────────────
        page_title = QLabel("Nhận Diện & Cảnh Báo")
        page_title.setObjectName("pageTitle")
        page_sub = QLabel(
            "Nhận diện giọng nói theo thời gian thực — "
            "tự động gửi SMS khi phát hiện tình huống"
        )
        page_sub.setObjectName("pageSub")
        outer.addWidget(page_title)
        outer.addWidget(page_sub)

        # ─────────────────────────────────
        # TOP ROW  (VĂN BẢN | SỰ KIỆN)
        # ─────────────────────────────────
        top_layout = QHBoxLayout()
        top_layout.setSpacing(16)

        # Panel 1 — VĂN BẢN NHẬN DIỆN
        self.speech_frame = self._make_panel("VĂN BẢN NHẬN DIỆN")
        self.speech_text  = QTextEdit()
        self.speech_text.setReadOnly(True)
        self.speech_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.speech_frame._body.addWidget(self.speech_text)
        # ASR status dot (xám = chưa chạy, xanh = OK, đỏ = offline)
        self._asr_dot = QLabel("●")
        self._asr_dot.setStyleSheet(
            "color:#95a5a6; font-size:14px; background:transparent;"
        )
        self._asr_dot.setToolTip("Trạng thái ASR")
        speech_clear = self._make_clear_btn()
        speech_clear.clicked.connect(self._clear_speech)

        self._mic_btn = QPushButton("🎙 Tắt Mic")
        self._mic_btn.setFixedHeight(26)
        self._mic_btn.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; border:none; "
            "border-radius:4px; padding:0 10px; font-size:13px; font-weight:600; }"
            "QPushButton:hover { background:#1e8449; }"
        )
        self._mic_btn.clicked.connect(self._toggle_mic)
        self._mic_btn.setEnabled(False)

        self.speech_frame._hdr.addStretch()
        self.speech_frame._hdr.addWidget(self._mic_btn)
        self.speech_frame._hdr.addWidget(self._asr_dot)
        self.speech_frame._hdr.addWidget(speech_clear)

        # Panel 2 — SỰ KIỆN & CẢNH BÁO
        self.event_frame = self._make_panel("SỰ KIỆN & CẢNH BÁO")
        self.event_text  = QTextEdit()
        self.event_text.setReadOnly(True)
        self.event_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.event_text.document().setMaximumBlockCount(2000)
        self.event_frame._body.addWidget(self.event_text)
        event_clear = self._make_clear_btn()
        event_clear.clicked.connect(self.event_text.clear)
        self.event_frame._hdr.addStretch()
        self.event_frame._hdr.addWidget(event_clear)

        top_layout.addWidget(self.speech_frame, 1)
        top_layout.addWidget(self.event_frame,  1)
        outer.addLayout(top_layout, 5)

        # ─────────────────────────────────
        # BOTTOM ROW  (NHẬT KÝ | TIN NHẮN)
        # ─────────────────────────────────
        bot_layout = QHBoxLayout()
        bot_layout.setSpacing(16)

        # Panel 3 — NHẬT KÝ HỆ THỐNG  (kỹ thuật, monospace)
        self.log_frame  = self._make_panel("NHẬT KÝ HỆ THỐNG")
        self.system_log = QTextEdit()
        self.system_log.setReadOnly(True)
        self.system_log.setStyleSheet(
            "QTextEdit { font-family: 'Consolas', monospace; font-size: 14px; }"
        )
        self.system_log.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.system_log.document().setMaximumBlockCount(2000)
        self.log_frame._body.addWidget(self.system_log)
        log_clear = self._make_clear_btn()
        log_clear.clicked.connect(self.system_log.clear)
        self.log_frame._hdr.addStretch()
        self.log_frame._hdr.addWidget(log_clear)

        # Panel 4 — TIN NHẮN QUA LẠI
        self.message_frame = self._make_panel("TIN NHẮN QUA LẠI")
        self.message_text  = QTextEdit()
        self.message_text.setReadOnly(True)
        self.message_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.message_text.document().setMaximumBlockCount(1000)
        self.message_frame._body.addWidget(self.message_text)
        msg_clear = self._make_clear_btn()
        msg_clear.clicked.connect(self.message_text.clear)
        self.message_frame._hdr.addStretch()
        self.message_frame._hdr.addWidget(msg_clear)

        bot_layout.addWidget(self.log_frame,     3)
        bot_layout.addWidget(self.message_frame, 2)
        outer.addLayout(bot_layout, 3)

    # ─────────────────────────────────
    # PANEL FACTORY
    # ─────────────────────────────────

    @staticmethod
    def _make_panel(title: str) -> QFrame:
        """
        /**
         * Chức năng: Tạo QFrame card với header cố định (36px) chứa tiêu đề và body layout
         *            mở rộng; expose card._body và card._hdr để caller thêm widget sau.
         * Tham số:
         *   title : tiêu đề panel hiển thị trong header
         * Trả về: QFrame card với thuộc tính _body (QVBoxLayout) và _hdr (QHBoxLayout)
         */
        """
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        hdr = QFrame()
        hdr.setObjectName("panelHeader")
        hdr.setFixedHeight(36)
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(14, 0, 8, 0)
        lbl = QLabel(title)
        lbl.setObjectName("panelTitle")
        hdr_layout.addWidget(lbl)
        card_layout.addWidget(hdr)

        body = QVBoxLayout()
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(0)
        card_layout.addLayout(body, 1)

        card._body = body
        card._hdr  = hdr_layout  # expose for adding widgets after creation
        return card

    @staticmethod
    def _make_clear_btn() -> QPushButton:
        """
        /**
         * Chức năng: Tạo nút "Xóa" nhỏ (40×22) dùng trong header panel để xóa nội dung
         *            QTextEdit tương ứng; đổi màu đỏ khi hover.
         * Tham số: Không
         * Trả về: QPushButton đã cấu hình style
         */
        """
        btn = QPushButton("Xóa")
        btn.setFixedSize(40, 22)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #95a5a6;
                border: 1px solid #d5dde5;
                border-radius: 3px;
                font-size: 11px;
                padding: 0;
            }
            QPushButton:hover {
                background: #fdedec;
                color: #c0392b;
                border-color: #e74c3c;
            }
        """)
        return btn

    def _clear_speech(self):
        """
        /**
         * Chức năng: Xóa bộ đệm _speech_lines và nội dung panel VĂN BẢN NHẬN DIỆN.
         * Tham số: Không
         * Trả về: None
         */
        """
        self._speech_lines.clear()
        self.speech_text.clear()
