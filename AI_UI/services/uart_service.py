import json
import threading
import time
import serial

from core.event_bus import bus
from core.state_manager import state_manager


class UARTService:

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo UARTService với tất cả thuộc tính về mặc định —
         *            chưa kết nối, chưa có thread đọc, chưa lưu cổng cuối.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đặt serial_port = None, running = False, thread = None.
         *   2. Tạo _lock để bảo vệ truy cập serial_port thread-safe.
         *   3. Lưu _last_port, _last_baudrate để tự kết nối lại sau lỗi.
         *   4. Đặt _user_disconnected = False.
         */
        """
        self.serial_port = None
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
        self._last_port = None
        self._last_baudrate = 115200
        self._user_disconnected = False

    # ─────────────────────────────────────────
    # CONNECT / DISCONNECT
    # ─────────────────────────────────────────

    def connect(self, port, baudrate=115200):
        """
        /**
         * Chức năng: Mở kết nối UART tới ESP32 trên cổng COM chỉ định,
         *            khởi động luồng đọc và phát tín hiệu uart_connected.
         * Tham số:
         *   - port     : tên cổng COM (ví dụ "COM3", "/dev/ttyUSB0")
         *   - baudrate : tốc độ baud (mặc định 115200)
         * Trả về: True nếu kết nối thành công, False nếu thất bại
         * Luồng hoạt động:
         *   1. Lấy lock; nếu đã có cổng mở thì trả True ngay.
         *   2. Mở serial.Serial với timeout 0.1s.
         *   3. Lưu thông tin cổng, đặt running=True, khởi động _read_loop thread.
         *   4. Cập nhật StateManager và phát bus.uart_connected.
         *   5. Trả False và log lỗi nếu exception.
         */
        """
        with self._lock:
            if self.serial_port and self.serial_port.is_open:
                return True
            try:
                self.serial_port = serial.Serial(port, baudrate, timeout=0.1)
                self.running = True
                self._last_port = port
                self._last_baudrate = baudrate
                self._user_disconnected = False
                self.thread = threading.Thread(target=self._read_loop, daemon=True)
                self.thread.start()
                state_manager.uart_connected = True
                bus.uart_connected.emit()
                print(f"[UART] Connected {port}")
                return True
            except Exception as e:
                print("[UART CONNECT]", e)
                state_manager.uart_connected = False
                return False

    def disconnect(self, user_initiated=True):
        """
        /**
         * Chức năng: Đóng kết nối UART, dừng luồng đọc và phát tín hiệu
         *            uart_disconnected.
         * Tham số:
         *   - user_initiated : True nếu người dùng chủ động ngắt (tắt auto-reconnect)
         * Trả về: True nếu ngắt thành công, False nếu exception
         * Luồng hoạt động:
         *   1. Lưu cờ _user_disconnected để _reconnect_loop biết không cần reconnect.
         *   2. Đặt running=False để thoát vòng lặp _read_loop.
         *   3. Đóng và xóa serial_port.
         *   4. Cập nhật StateManager và phát bus.uart_disconnected.
         */
        """
        self._user_disconnected = user_initiated
        try:
            self.running = False
            with self._lock:
                if self.serial_port:
                    if self.serial_port.is_open:
                        self.serial_port.close()
                    self.serial_port = None
            state_manager.uart_connected = False
            bus.uart_disconnected.emit()
            print("[UART] Disconnected")
            return True
        except Exception as e:
            print("[UART DISCONNECT]", e)
            return False

    def is_connected(self):
        """
        /**
         * Chức năng: Kiểm tra xem cổng serial có đang mở hay không.
         * Tham số: Không
         * Trả về: True nếu đang kết nối, False nếu không
         * Luồng hoạt động:
         *   1. Lấy lock và kiểm tra serial_port != None và is_open.
         */
        """
        with self._lock:
            return bool(self.serial_port and self.serial_port.is_open)

    # ─────────────────────────────────────────
    # SEND
    # ─────────────────────────────────────────

    def send_packet(self, packet):
        """
        /**
         * Chức năng: Serialize dict thành JSON và gửi qua UART kèm ký tự xuống dòng.
         * Tham số:
         *   - packet : dict chứa dữ liệu gói tin cần gửi
         * Trả về: None
         * Luồng hoạt động:
         *   1. Kiểm tra kết nối; thoát nếu chưa kết nối.
         *   2. Serialize packet thành JSON string (ensure_ascii=False cho UTF-8).
         *   3. Lấy lock và ghi data + "\n" ra serial port.
         *   4. Nếu lỗi: gọi disconnect(user_initiated=False) để trigger reconnect.
         */
        """
        if not self.is_connected():
            print("[UART] NOT CONNECTED")
            return
        try:
            data = json.dumps(packet, ensure_ascii=False)
            with self._lock:
                if self.serial_port and self.serial_port.is_open:
                    self.serial_port.write((data + "\n").encode())
        except Exception as e:
            print("[UART SEND]", e)
            self.disconnect(user_initiated=False)

    def check_system(self):
        """
        /**
         * Chức năng: Gửi lệnh CHECK_SYSTEM xuống ESP32 — yêu cầu kiểm tra
         *            đầy đủ SIM (gọi checkSIMStatus trên ESP32, mất ~5-10s).
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo gói COMMAND CHECK_SYSTEM với packet_id timestamp.
         *   2. Gọi send_packet() để gửi qua UART.
         */
        """
        self.send_packet({
            "type": "COMMAND", "command": "CHECK_SYSTEM",
            "packet_id": f"UI_{int(time.time())}",
            "source": "AI_UI", "target": "ESP32",
            "timestamp": int(time.time())
        })

    def request_system_state(self):
        """
        /**
         * Chức năng: Gửi lệnh GET_SYSTEM_STATE xuống ESP32 — trả về trạng thái
         *            hiện tại ngay lập tức (không re-check SIM, phản hồi nhanh).
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo gói COMMAND GET_SYSTEM_STATE với packet_id timestamp.
         *   2. Gọi send_packet() để gửi qua UART.
         */
        """
        self.send_packet({
            "type": "COMMAND", "command": "GET_SYSTEM_STATE",
            "packet_id": f"UI_{int(time.time())}",
            "source": "AI_UI", "target": "ESP32",
            "timestamp": int(time.time())
        })

    def sync_all_contacts(self):
        """
        /**
         * Chức năng: Đồng bộ toàn bộ danh bạ từ database xuống ESP32 —
         *            chạy trên daemon thread để không chặn UI.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Khởi động daemon thread chạy _sync_all_thread().
         */
        """
        import threading
        threading.Thread(
            target=self._sync_all_thread,
            daemon=True
        ).start()

    def _sync_all_thread(self):
        """
        /**
         * Chức năng: Gửi SYNC_CONTACTS_CLEAR rồi gửi từng liên hệ xuống
         *            ESP32 với khoảng nghỉ nhỏ giữa các gói.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Chờ 0.5s để UART ổn định.
         *   2. Gửi SYNC_CONTACTS_CLEAR để xóa danh bạ cũ trên ESP32.
         *   3. Tải toàn bộ liên hệ từ database.
         *   4. Gửi từng liên hệ qua SYNC_CONTACT với delay 50ms.
         */
        """
        from services.database_service import database_service
        time.sleep(0.5)
        self.send_packet({
            "type": "COMMAND", "command": "SYNC_CONTACTS_CLEAR",
            "packet_id": f"UI_{int(time.time())}",
            "source": "AI_UI", "target": "ESP32",
            "timestamp": int(time.time())
        })
        time.sleep(0.1)
        contacts = database_service.load_contacts()
        for c in contacts:
            contact_id, name, phone, relation, _ = c
            self.send_packet({
                "type": "COMMAND", "command": "SYNC_CONTACT",
                "packet_id": f"UI_{int(time.time())}",
                "source": "AI_UI", "target": "ESP32",
                "timestamp": int(time.time()),
                "payload": {
                    "id": contact_id,
                    "phone": phone,
                    "name": name,
                    "relation": relation
                }
            })
            time.sleep(0.05)

    def push_contact(self, contact_id, name, phone, relation):
        """
        /**
         * Chức năng: Đẩy một liên hệ mới/cập nhật xuống ESP32 sau khi
         *            thêm hoặc chỉnh sửa trong database.
         * Tham số:
         *   - contact_id : ID duy nhất của liên hệ
         *   - name       : tên liên hệ
         *   - phone      : số điện thoại
         *   - relation   : vai trò/quan hệ (family, caregiver...)
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo gói SYNC_CONTACT với payload đầy đủ.
         *   2. Gọi send_packet().
         */
        """
        self.send_packet({
            "type": "COMMAND", "command": "SYNC_CONTACT",
            "packet_id": f"UI_{int(time.time())}",
            "source": "AI_UI", "target": "ESP32",
            "timestamp": int(time.time()),
            "payload": {
                "id": contact_id,
                "phone": phone,
                "name": name,
                "relation": relation
            }
        })

    def push_delete_contact(self, contact_id):
        """
        /**
         * Chức năng: Thông báo ESP32 xóa một liên hệ khỏi bộ nhớ.
         * Tham số:
         *   - contact_id : ID của liên hệ cần xóa
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo gói DELETE_CONTACT với payload chứa id.
         *   2. Gọi send_packet().
         */
        """
        self.send_packet({
            "type": "COMMAND", "command": "DELETE_CONTACT",
            "packet_id": f"UI_{int(time.time())}",
            "source": "AI_UI", "target": "ESP32",
            "timestamp": int(time.time()),
            "payload": {"id": contact_id}
        })

    def send_contact_result(self, status, reason=""):
        """
        /**
         * Chức năng: Gửi kết quả xử lý yêu cầu ADD_CONTACT từ ESP32 về
         *            lại ESP32 (SUCCESS hoặc ERROR với mã lỗi).
         * Tham số:
         *   - status : "SUCCESS" hoặc mã lỗi khác
         *   - reason : mã lỗi chi tiết (error_code) khi status != "SUCCESS"
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo gói RESPONSE ADD_CONTACT với status và error_code.
         *   2. Gọi send_packet().
         */
        """
        self.send_packet({
            "type": "RESPONSE", "command": "ADD_CONTACT",
            "packet_id": f"UI_{int(time.time())}",
            "source": "AI_UI", "target": "ESP32",
            "timestamp": int(time.time()),
            "status": "SUCCESS" if status == "SUCCESS" else "ERROR",
            "error_code": reason
        })

    # ─────────────────────────────────────────
    # READ LOOP
    # ─────────────────────────────────────────

    def _read_loop(self):
        """
        /**
         * Chức năng: Vòng lặp đọc liên tục từ UART — chạy trên daemon thread
         *            cho đến khi mất kết nối hoặc self.running = False.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đọc một dòng từ serial port (readline).
         *   2. Phát bus.uart_received với chuỗi thô.
         *   3. Parse JSON và gọi _route() để điều phối gói tin.
         *   4. Nếu exception: disconnect và khởi động _reconnect_loop nếu chưa
         *      bị ngắt bởi người dùng.
         */
        """
        while self.running:
            try:
                if not self.is_connected():
                    time.sleep(0.1)
                    continue
                with self._lock:
                    sp = self.serial_port
                if sp is None or not sp.is_open:
                    time.sleep(0.1)
                    continue
                line = sp.readline().decode(errors="ignore").strip()
                if not line:
                    continue
                bus.uart_received.emit(line)
                try:
                    self._route(json.loads(line))
                except Exception as e:
                    print(f"[UART ROUTE] {e} | raw={line[:80]}")
            except Exception as e:
                print("[UART RX]", e)
                self.disconnect(user_initiated=False)
                # Tự động thử kết nối lại nếu không phải user ngắt
                if self._last_port:
                    threading.Thread(
                        target=self._reconnect_loop,
                        daemon=True
                    ).start()
                break

    def _reconnect_loop(self):
        """
        /**
         * Chức năng: Cố gắng kết nối lại tự động mỗi 5 giây sau khi UART
         *            bị ngắt bởi lỗi (không phải do người dùng).
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lặp khi chưa kết nối và người dùng chưa ngắt chủ động.
         *   2. Chờ 5 giây rồi gọi connect() với thông tin cổng cuối.
         */
        """
        attempt = 0
        while not self.is_connected() and not self._user_disconnected:
            time.sleep(5)
            attempt += 1
            print(f"[UART] Auto-reconnect attempt {attempt} on {self._last_port}...")
            self.connect(self._last_port, self._last_baudrate)

    # ─────────────────────────────────────────
    # PACKET ROUTING
    # Gộp từ core/packet_router.py
    # ─────────────────────────────────────────

    def _ack(self, packet: dict):
        """
        /**
         * Chức năng: Gửi gói ACK phản hồi cho một gói tin có packet_id.
         * Tham số:
         *   - packet : dict gói tin cần ACK (phải có trường "packet_id")
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy packet_id từ gói.
         *   2. Nếu có packet_id: gửi gói ACK với packet_id đó.
         */
        """
        pid = packet.get("packet_id", "")
        if pid:
            self.send_packet({"type": "ACK", "packet_id": pid})

    def _route(self, packet: dict):
        """
        /**
         * Chức năng: Điều phối gói tin nhận từ ESP32 tới handler phù hợp
         *            bằng cách phát signal trên EventBus theo command.
         * Tham số:
         *   - packet : dict đã parse từ JSON UART
         * Trả về: None
         * Luồng hoạt động:
         *   1. Trích command và payload từ packet.
         *   2. Theo command: phát signal tương ứng trên bus hoặc cập nhật StateManager.
         *      - START/STOP_MANUAL_SMS → bus.manual_sms_started/stopped
         *      - HEARTBEAT → cập nhật last_heartbeat
         *      - SYSTEM_STATE → update_from_packet + bus.system_state_updated
         *      - ADD_CONTACT REQUEST → bus.add_contact_request
         *      - NEW_SMS/SMS_DELIVERY/SMS_RESULT → bus tương ứng
         *      - SOS_ALERT/STOP_AUDIO → ACK + bus tương ứng
         */
        """
        command = packet.get("command", "")
        payload = packet.get("payload", {})

        if command == "START_MANUAL_SMS":
            bus.manual_sms_started.emit()
        elif command == "STOP_MANUAL_SMS":
            bus.manual_sms_stopped.emit()
        elif command == "HEARTBEAT":
            state_manager.last_heartbeat = time.time()
        elif command == "SYSTEM_STATE":
            state_manager.update_from_packet(payload)
            state_manager.waiting_system_response = False
            bus.system_state_updated.emit()
        elif command == "ADD_CONTACT":
            if packet.get("type", "") == "REQUEST":
                enriched = dict(payload)
                enriched["_packet_id"] = packet.get("packet_id", "")
                bus.add_contact_request.emit(enriched)
        elif command == "NEW_SMS":
            self._ack(packet)
            bus.new_sms.emit(payload)
        elif command == "SMS_DELIVERY":
            bus.sms_delivery.emit({
                "phone":  payload.get("phone",  ""),
                "status": payload.get("status", ""),
                "mr":     payload.get("mr",     -1),
            })
        elif command == "SMS_RESULT":
            bus.sms_result.emit({
                "packet_id": packet.get("packet_id", ""),
                "phone": payload.get("phone", ""),
                "status": payload.get("status", ""),
            })
        elif command == "SOS_ALERT":
            self._ack(packet)
            bus.sos_alert.emit()
        elif command == "STOP_AUDIO":
            self._ack(packet)
            bus.stop_audio.emit()


uart_service = UARTService()
