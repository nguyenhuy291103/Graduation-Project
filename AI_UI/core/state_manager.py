class StateManager:
    """
    Lưu trạng thái runtime toàn cục — không persist, reset khi khởi động.
    Truy cập qua singleton `state_manager`.

    Viết từ nhiều thread (uart_service, tts_service, recognition_worker).
    Đọc từ mọi nơi — không có lock vì các trường đều là atomic Python types.
    """

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo StateManager và đặt toàn bộ trạng thái về
         *            giá trị mặc định ban đầu bằng cách gọi reset().
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi reset() để khởi tạo tất cả các trường trạng thái.
         */
        """

        self.reset()

    # =====================================
    # RESET
    # =====================================

    def reset(self):
        """
        /**
         * Chức năng: Đặt lại toàn bộ trạng thái runtime về giá trị mặc định.
         *            Dùng khi khởi động hoặc khi UART mất kết nối.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Xóa trạng thái kết nối UART.
         *   2. Xóa toàn bộ trạng thái ESP32 (SIM, mạng, SMS, tín hiệu).
         *   3. Xóa timestamp heartbeat cuối.
         *   4. Đặt lại trạng thái audio laptop (mic, loa, TTS).
         *   5. Xóa cờ chờ phản hồi kết nối.
         */
        """

        # ================================
        # UART
        # ================================

        self.uart_connected = False

        # ================================
        # ESP32 STATE
        # ================================

        self.sim_module = False

        self.sim_inserted = False

        self.network_registered = False

        self.sms_ready = False

        self.signal = 0

        # ================================
        # HEARTBEAT
        # ================================

        self.last_heartbeat = 0

        # ================================
        # LAPTOP AUDIO
        # ================================

        self.mic_enabled = False

        self.mic_muted = False

        self.speaker_volume = 70

        # ================================
        # TTS MODE
        # Khi True: RecognitionWorker skip
        # toàn bộ xử lý nghiệp vụ để
        # tránh false detection từ loa.
        # ================================

        self.tts_active = False

        self.last_tts_text = ""

        self.last_tts_time = 0.0

        # ================================
        # CONNECTION
        # ================================

        self.waiting_system_response = False

    # =====================================
    # UPDATE FROM ESP32
    # =====================================

    def update_from_packet(
        self,
        payload
    ):
        """
        /**
         * Chức năng: Cập nhật trạng thái ESP32 từ payload của gói SYSTEM_STATE
         *            nhận qua UART.
         * Tham số:
         *   - payload : dict chứa các trường trạng thái từ ESP32
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đọc và cập nhật trạng thái module SIM.
         *   2. Đọc và cập nhật cờ SIM đã cắm.
         *   3. Đọc và cập nhật trạng thái đăng ký mạng.
         *   4. Đọc và cập nhật cờ SMS sẵn sàng.
         *   5. Đọc và cập nhật cường độ tín hiệu.
         */
        """

        # ================================
        # SIM READY
        # ================================

        self.sim_module = (
            payload.get(
                "sim_ready",
                payload.get(
                    "sim_module",
                    False
                )
            )
        )

        # ================================
        # SIM INSERTED
        # ================================

        self.sim_inserted = (
            payload.get(
                "sim_inserted",
                False
            )
        )

        # ================================
        # NETWORK
        # ================================

        self.network_registered = (
            payload.get(
                "network_ready",
                payload.get(
                    "network_registered",
                    False
                )
            )
        )

        # ================================
        # SMS
        # ================================

        self.sms_ready = (
            payload.get(
                "sms_ready",
                False
            )
        )

        # ================================
        # SIGNAL
        # ================================

        self.signal = (
            payload.get(
                "signal_strength",
                payload.get(
                    "signal",
                    0
                )
            )
        )

state_manager = StateManager()
