import time

TIMEOUT_NO_TEXT_SEC      = 15.0   # 15s không có text mới → tự gửi
TIMEOUT_MAX_DURATION_SEC = 60.0   # 60s tổng → tự gửi
EMPTY_SMS_WINDOW_SEC     = 120.0  # cửa sổ 2 phút cho anti-spam
EMPTY_SMS_MAX_PER_WINDOW = 4      # tối đa 4 cảnh báo / 2 phút


class ManualSMSMode:
    """
    State machine cho chức năng Gửi tin nhắn chủ động bằng giọng nói.

    Vòng đời:
        activate()        → bắt đầu thu thập (MANUAL_SMS_MODE ON)
        add_text(text)    → thêm câu ASR vào bộ nhớ đệm
        stop()            → kết thúc thủ công (phím B)
        check_timeouts()  → gọi mỗi 1 giây từ QTimer

    Callbacks (set trước khi gọi activate):
        on_activate()              → hiển thị UI + TTS hướng dẫn
        on_finalize(text, reason)  → xử lý gửi SMS và reset
    """

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo ManualSMSMode với tất cả trạng thái về mặc định
         *            và hai callback None chờ được gán từ bên ngoài.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đặt _active = False, _text_parts = [], timestamp về 0.
         *   2. Khởi tạo bộ đếm anti-spam cảnh báo rỗng.
         *   3. Đặt on_activate và on_finalize = None.
         */
        """
        self._active = False
        self._text_parts: list = []
        self._last_text_time = 0.0
        self._start_time = 0.0

        # Anti-spam cho cảnh báo không có nội dung
        self._empty_count = 0
        self._empty_window_start = 0.0

        self.on_activate = None   # callable() -> None
        self.on_finalize = None   # callable(text: str, reason: str) -> None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        """
        /**
         * Chức năng: Kiểm tra xem ManualSMSMode có đang hoạt động không.
         * Tham số: Không
         * Trả về: True nếu đang thu thập giọng nói, False nếu không
         * Luồng hoạt động:
         *   1. Trả về giá trị _active.
         */
        """
        return self._active

    def activate(self):
        """
        /**
         * Chức năng: Kích hoạt MANUAL_SMS_MODE — bắt đầu thu thập giọng nói.
         *            Bỏ qua nếu đang hoạt động.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Kiểm tra nếu đã active thì thoát ngay.
         *   2. Đặt _active = True, xóa bộ đệm text, ghi timestamp bắt đầu.
         *   3. Gọi callback on_activate() nếu đã được đăng ký.
         */
        """
        if self._active:
            return
        self._active = True
        self._text_parts = []
        now = time.time()
        self._last_text_time = now
        self._start_time = now
        if self.on_activate:
            self.on_activate()

    def stop(self):
        """
        /**
         * Chức năng: Kết thúc thu thập thủ công (người dùng nhấn phím B).
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Kiểm tra nếu không active thì thoát.
         *   2. Gọi _finalize() với lý do "manual_stop".
         */
        """
        if not self._active:
            return
        self._finalize("manual_stop")

    def add_text(self, text: str):
        """
        /**
         * Chức năng: Thêm câu ASR vào bộ đệm khi đang ở chế độ thu thập.
         * Tham số:
         *   - text : câu vừa nhận diện được từ ASR engine
         * Trả về: None
         * Luồng hoạt động:
         *   1. Bỏ qua nếu không đang active.
         *   2. Strip whitespace; nếu không rỗng thì thêm vào _text_parts.
         *   3. Cập nhật _last_text_time để reset timeout.
         */
        """
        if not self._active:
            return
        text = text.strip()
        if text:
            self._text_parts.append(text)
            self._last_text_time = time.time()

    def check_timeouts(self):
        """
        /**
         * Chức năng: Kiểm tra timeout và tự động kết thúc thu thập nếu
         *            hết thời gian — gọi định kỳ mỗi 1 giây từ QTimer.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Bỏ qua nếu không active.
         *   2. Tính thời gian đã qua và thời gian từ lần nhận text cuối.
         *   3. Nếu vượt TIMEOUT_MAX_DURATION_SEC → finalize "timeout_max_duration".
         *   4. Nếu vượt TIMEOUT_NO_TEXT_SEC → finalize "timeout_no_text".
         */
        """
        if not self._active:
            return
        now = time.time()
        elapsed = now - self._start_time
        since_last = now - self._last_text_time
        if elapsed >= TIMEOUT_MAX_DURATION_SEC:
            self._finalize("timeout_max_duration")
        elif since_last >= TIMEOUT_NO_TEXT_SEC:
            self._finalize("timeout_no_text")

    def can_send_empty_warning(self) -> bool:
        """
        /**
         * Chức năng: Kiểm tra anti-spam cho SMS cảnh báo không có nội dung
         *            (khi người dùng kích hoạt nhưng không nói gì).
         * Tham số: Không
         * Trả về: True nếu được phép gửi, False nếu đã vượt giới hạn
         * Luồng hoạt động:
         *   1. Nếu đã qua cửa sổ EMPTY_SMS_WINDOW_SEC: reset bộ đếm.
         *   2. Nếu _empty_count < MAX_PER_WINDOW: tăng đếm và trả True.
         *   3. Ngược lại trả False (chặn spam).
         */
        """
        now = time.time()
        if now - self._empty_window_start >= EMPTY_SMS_WINDOW_SEC:
            self._empty_count = 0
            self._empty_window_start = now
        if self._empty_count < EMPTY_SMS_MAX_PER_WINDOW:
            self._empty_count += 1
            return True
        return False

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _finalize(self, reason: str):
        """
        /**
         * Chức năng: Kết thúc quá trình thu thập, ghép các đoạn text thành
         *            một chuỗi hoàn chỉnh và kích hoạt callback on_finalize.
         * Tham số:
         *   - reason : lý do kết thúc ("manual_stop", "timeout_no_text",
         *              "timeout_max_duration")
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đặt _active = False.
         *   2. Ghép _text_parts thành chuỗi cuối cùng.
         *   3. Gọi on_finalize(text, reason) nếu đã đăng ký.
         */
        """
        self._active = False
        text = " ".join(self._text_parts).strip()
        if self.on_finalize:
            self.on_finalize(text, reason)
