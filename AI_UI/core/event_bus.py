import threading

from PyQt5.QtCore import QObject

from PyQt5.QtCore import pyqtSignal


class EventBus(QObject):
    """
    Kênh sự kiện toàn cục (singleton).
    Tất cả signal phải được connect với Qt.QueuedConnection khi kết nối
    từ background thread sang slot trên main thread.
    """

    # ── UART ────────────────────────────────────────────
    uart_connected    = pyqtSignal()        # ESP32 kết nối thành công
    uart_disconnected = pyqtSignal()        # ESP32 mất kết nối
    uart_received     = pyqtSignal(str)     # raw JSON string nhận từ ESP32

    # ── TRẠNG THÁI HỆ THỐNG ─────────────────────────────
    system_state_updated = pyqtSignal()     # ESP32 trả về SYSTEM_STATE packet

    # ── DANH BẠ ─────────────────────────────────────────
    add_contact_request = pyqtSignal(dict)  # ESP32 yêu cầu thêm liên hệ mới

    # ── SMS ─────────────────────────────────────────────
    new_sms              = pyqtSignal(dict)      # SMS đến từ người thân
    sms_result           = pyqtSignal(dict)      # kết quả gửi SMS (SUCCESS/FAILED)
    sms_delivery         = pyqtSignal(dict)      # delivery report (đã tới tay người nhận)
    # slot(int), nhãn người gửi(str), nội dung(str)
    quick_message_triggered = pyqtSignal(int, str, str)

    # ── MANUAL SMS ───────────────────────────────────────
    manual_sms_started = pyqtSignal()       # ESP32 nhấn nút B → bắt đầu ghi âm
    manual_sms_stopped = pyqtSignal()       # ESP32 nhấn nút B lần 2 → kết thúc

    # ── SOS ─────────────────────────────────────────────
    sos_alert = pyqtSignal()                # ESP32 nhấn nút SOS khẩn cấp

    # ── AUDIO ────────────────────────────────────────────
    stop_audio = pyqtSignal()               # ESP32 nhấn nút A → dừng TTS

    # ── THÔNG BÁO UI ─────────────────────────────────────
    notification = pyqtSignal(str)          # thông báo ngắn hiển thị trên UI

    # ── NHẬT KÝ ──────────────────────────────────────────
    log_updated = pyqtSignal()              # có bản ghi mới trong bảng logs (DB)


# Lazy proxy: EventBus() chỉ được tạo khi attribute đầu tiên được truy cập.
# Đảm bảo QApplication đã tồn tại trước khi QObject được khởi tạo —
# tránh lỗi "QObject: Cannot create children for a parent that is in a different thread".
class _BusProxy:

    _instance = None
    _lock = threading.Lock()

    def _get(self):
        """
        /**
         * Chức năng: Trả về instance EventBus duy nhất, tạo mới nếu chưa có
         *            (double-checked locking để thread-safe).
         * Tham số: Không
         * Trả về: EventBus — instance singleton
         * Luồng hoạt động:
         *   1. Kiểm tra nhanh không lock xem đã có instance chưa.
         *   2. Nếu chưa, lấy lock và kiểm tra lại (double-check).
         *   3. Tạo EventBus mới và lưu vào _instance.
         *   4. Trả về _instance.
         */
        """
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = EventBus()
        return self._instance

    def __getattr__(self, name):
        """
        /**
         * Chức năng: Chuyển tiếp mọi truy cập thuộc tính sang EventBus thật,
         *            kích hoạt khởi tạo lazy nếu cần.
         * Tham số:
         *   - name : tên thuộc tính (signal hoặc phương thức của EventBus)
         * Trả về: Thuộc tính tương ứng trên EventBus instance
         * Luồng hoạt động:
         *   1. Gọi _get() để lấy EventBus singleton.
         *   2. Trả về getattr(instance, name).
         */
        """
        return getattr(self._get(), name)


bus = _BusProxy()
