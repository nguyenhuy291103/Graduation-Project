import os
import re
import sqlite3
from datetime import datetime


class DatabaseService:

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo DatabaseService — xác định đường dẫn file DB
         *            và tạo thư mục database nếu chưa tồn tại.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Xác định root_dir từ vị trí file nguồn.
         *   2. Đặt db_path = root_dir/database/emergency.db.
         *   3. Tạo thư mục cha nếu chưa có.
         */
        """
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(root_dir, "database", "emergency.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _conn(self):
        """
        /**
         * Chức năng: Tạo và trả về một kết nối SQLite mới tới database.
         * Tham số: Không
         * Trả về: sqlite3.Connection
         * Luồng hoạt động:
         *   1. Gọi sqlite3.connect(db_path) và trả về connection.
         */
        """
        return sqlite3.connect(self.db_path)

    # ─────────────────────────────────────────
    # INIT
    # ─────────────────────────────────────────

    def initialize(self):
        """
        /**
         * Chức năng: Tạo tất cả bảng cần thiết nếu chưa có, nâng cấp schema
         *            cũ và xóa log quá 30 ngày.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo bảng contacts, contact_roles, logs nếu chưa có.
         *   2. Thêm cột relation vào contacts nếu nâng cấp từ schema cũ.
         *   3. Tạo bảng quick_messages và đảm bảo đủ 10 slot.
         *   4. Xóa log cũ hơn 30 ngày.
         */
        """
        conn = self._conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                contact_id TEXT PRIMARY KEY,
                name       TEXT DEFAULT '',
                phone      TEXT UNIQUE NOT NULL,
                relation   TEXT DEFAULT ''
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS contact_roles (
                contact_id TEXT NOT NULL,
                role       TEXT NOT NULL,
                PRIMARY KEY (contact_id, role)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                message   TEXT NOT NULL
            )
        """)
        conn.commit()
        # Thêm cột relation nếu nâng cấp từ schema cũ (không có cột này)
        try:
            c.execute("ALTER TABLE contacts ADD COLUMN relation TEXT DEFAULT ''")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Cột đã tồn tại — bình thường khi không phải lần đầu chạy
        # Bảng tin nhắn nhanh (slot 1-10 → nội dung văn bản)
        c.execute("""
            CREATE TABLE IF NOT EXISTS quick_messages (
                slot    INTEGER PRIMARY KEY,
                text    TEXT    DEFAULT ''
            )
        """)
        # Đảm bảo đủ 10 slot tồn tại
        for slot in range(1, 11):
            c.execute(
                "INSERT OR IGNORE INTO quick_messages (slot, text) VALUES (?, ?)",
                (slot, "")
            )
        conn.commit()
        # Xóa log cũ hơn 30 ngày để tránh DB phình to
        try:
            c.execute(
                "DELETE FROM logs WHERE timestamp < datetime('now', '-30 days')"
            )
            conn.commit()
        except Exception:
            pass
        conn.close()
        print("[DATABASE] READY")

    # ─────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────

    @staticmethod
    def _is_valid_phone(phone: str) -> bool:
        """
        /**
         * Chức năng: Kiểm tra số điện thoại có đúng định dạng Việt Nam
         *            (bắt đầu bằng 0, tổng 10 chữ số).
         * Tham số:
         *   - phone : chuỗi số điện thoại cần kiểm tra
         * Trả về: True nếu hợp lệ, False nếu không
         * Luồng hoạt động:
         *   1. Dùng regex r'^0\d{9}$' để kiểm tra định dạng.
         */
        """
        return bool(re.match(r'^0\d{9}$', phone))

    # ─────────────────────────────────────────
    # CONTACT CRUD
    # ─────────────────────────────────────────

    def add_contact(self, contact_id, name, phone, relation="", roles=None):
        """
        /**
         * Chức năng: Thêm liên hệ mới vào database với kiểm tra trùng lặp.
         * Tham số:
         *   - contact_id : ID duy nhất của liên hệ
         *   - name       : tên hiển thị
         *   - phone      : số điện thoại (phải hợp lệ và chưa tồn tại)
         *   - relation   : quan hệ (mặc định "")
         *   - roles      : list vai trò (mặc định ["CHĂM SÓC"])
         * Trả về: tuple (bool, str) — (True, "SUCCESS") hoặc (False, mã lỗi)
         * Luồng hoạt động:
         *   1. Kiểm tra định dạng phone; trả lỗi INVALID_PHONE nếu sai.
         *   2. Kiểm tra trùng contact_id và phone; trả lỗi tương ứng.
         *   3. INSERT vào contacts và contact_roles.
         *   4. Commit và đóng kết nối.
         */
        """
        if roles is None:
            roles = ["CHĂM SÓC"]
        elif isinstance(roles, str):
            roles = [roles]
        if not self._is_valid_phone(phone):
            return False, "INVALID_PHONE"
        conn = self._conn()
        c = conn.cursor()
        try:
            if c.execute(
                "SELECT 1 FROM contacts WHERE contact_id = ?", (contact_id,)
            ).fetchone():
                conn.close()
                return False, "ID_EXISTS"
            if c.execute(
                "SELECT 1 FROM contacts WHERE phone = ?", (phone,)
            ).fetchone():
                conn.close()
                return False, "PHONE_EXISTS"
            c.execute(
                "INSERT INTO contacts (contact_id, name, phone, relation) VALUES (?,?,?,?)",
                (contact_id, name, phone, relation)
            )
            for role in roles:
                c.execute(
                    "INSERT OR IGNORE INTO contact_roles (contact_id, role) VALUES (?,?)",
                    (contact_id, role)
                )
            conn.commit()
            conn.close()
            return True, "SUCCESS"
        except Exception as e:
            conn.close()
            print("[DATABASE]", e)
            return False, "DATABASE_ERROR"

    def delete_contact(self, contact_id):
        """
        /**
         * Chức năng: Xóa liên hệ và tất cả vai trò liên quan theo contact_id.
         * Tham số:
         *   - contact_id : ID của liên hệ cần xóa
         * Trả về: True nếu thành công, False nếu exception
         * Luồng hoạt động:
         *   1. Xóa trong contact_roles trước (FK cascade thủ công).
         *   2. Xóa trong contacts.
         *   3. Commit và đóng kết nối.
         */
        """
        try:
            conn = self._conn()
            c = conn.cursor()
            c.execute("DELETE FROM contact_roles WHERE contact_id = ?", (contact_id,))
            c.execute("DELETE FROM contacts WHERE contact_id = ?", (contact_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print("[DATABASE]", e)
            return False

    def update_contact(self, old_id, new_id, new_name, new_phone, relation="", roles=None):
        """
        /**
         * Chức năng: Cập nhật thông tin liên hệ, bao gồm thay đổi ID và SĐT
         *            với kiểm tra trùng lặp.
         * Tham số:
         *   - old_id    : ID hiện tại của liên hệ
         *   - new_id    : ID mới (có thể giống old_id)
         *   - new_name  : tên mới
         *   - new_phone : SĐT mới
         *   - relation  : quan hệ mới
         *   - roles     : danh sách vai trò mới
         * Trả về: tuple (bool, str) — (True, "SUCCESS") hoặc (False, mã lỗi)
         * Luồng hoạt động:
         *   1. Kiểm tra trùng new_id và new_phone với record khác.
         *   2. UPDATE contacts SET contact_id, name, phone, relation.
         *   3. Xóa toàn bộ roles cũ và INSERT roles mới.
         *   4. Commit và đóng kết nối.
         */
        """
        if roles is None:
            roles = ["CHĂM SÓC"]
        elif isinstance(roles, str):
            roles = [roles]
        conn = self._conn()
        c = conn.cursor()
        try:
            if c.execute(
                "SELECT 1 FROM contacts WHERE contact_id = ? AND contact_id != ?",
                (new_id, old_id)
            ).fetchone():
                conn.close()
                return False, "ID_EXISTS"
            if c.execute(
                "SELECT 1 FROM contacts WHERE phone = ? AND contact_id != ?",
                (new_phone, old_id)
            ).fetchone():
                conn.close()
                return False, "PHONE_EXISTS"
            c.execute(
                "UPDATE contacts SET contact_id=?, name=?, phone=?, relation=? WHERE contact_id=?",
                (new_id, new_name, new_phone, relation, old_id)
            )
            c.execute("DELETE FROM contact_roles WHERE contact_id = ?", (old_id,))
            for role in roles:
                c.execute(
                    "INSERT OR IGNORE INTO contact_roles (contact_id, role) VALUES (?,?)",
                    (new_id, role)
                )
            conn.commit()
            conn.close()
            return True, "SUCCESS"
        except Exception as e:
            conn.close()
            print("[DATABASE]", e)
            return False, "DATABASE_ERROR"

    def load_contacts(self):
        """
        /**
         * Chức năng: Tải toàn bộ danh sách liên hệ cùng vai trò tổng hợp.
         * Tham số: Không
         * Trả về: list of tuple (contact_id, name, phone, relation, roles_str)
         * Luồng hoạt động:
         *   1. JOIN contacts với contact_roles, GROUP_CONCAT roles.
         *   2. Sắp xếp theo contact_id.
         *   3. Trả danh sách; [] nếu exception.
         */
        """
        try:
            conn = self._conn()
            rows = conn.cursor().execute("""
                SELECT c.contact_id, c.name, c.phone, c.relation,
                       COALESCE(GROUP_CONCAT(cr.role, ' | '), '')
                FROM contacts c
                LEFT JOIN contact_roles cr ON c.contact_id = cr.contact_id
                GROUP BY c.contact_id
                ORDER BY c.contact_id
            """).fetchall()
            conn.close()
            return rows
        except Exception as e:
            print("[DATABASE]", e)
            return []

    def get_contact_roles(self, contact_id: str) -> list:
        """
        /**
         * Chức năng: Lấy danh sách vai trò của một liên hệ theo ID.
         * Tham số:
         *   - contact_id : ID của liên hệ
         * Trả về: list[str] các vai trò; [] nếu không có hoặc exception
         * Luồng hoạt động:
         *   1. SELECT role FROM contact_roles WHERE contact_id = ?.
         *   2. Trả list chuỗi role.
         */
        """
        try:
            conn = self._conn()
            rows = conn.cursor().execute(
                "SELECT role FROM contact_roles WHERE contact_id = ?",
                (contact_id,)
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception as e:
            print("[DATABASE]", e)
            return []

    def get_contact_by_phone(self, phone: str):
        """
        /**
         * Chức năng: Tra cứu liên hệ theo số điện thoại, hỗ trợ cả định dạng
         *            quốc tế +84XXXXXXXXX và nội địa 0XXXXXXXXX.
         * Tham số:
         *   - phone : số điện thoại cần tra cứu
         * Trả về: tuple (name, relation) nếu tìm thấy, None nếu không có
         * Luồng hoạt động:
         *   1. Chuẩn hóa +84XXXXXXXXX → 0XXXXXXXXX.
         *   2. SELECT name, relation FROM contacts WHERE phone = normalized.
         */
        """
        # Normalize international format: +84XXXXXXXXX → 0XXXXXXXXX
        normalized = phone
        if phone.startswith("+84") and len(phone) == 12:
            normalized = "0" + phone[3:]
        try:
            conn = self._conn()
            row = conn.cursor().execute(
                "SELECT name, relation FROM contacts WHERE phone = ?",
                (normalized,)
            ).fetchone()
            conn.close()
            return row  # (name, relation) or None
        except Exception as e:
            print("[DATABASE]", e)
            return None

    def get_contacts_by_role(self, role: str) -> list:
        """
        /**
         * Chức năng: Lấy danh sách liên hệ có vai trò chỉ định.
         * Tham số:
         *   - role : tên vai trò cần lọc
         * Trả về: list of tuple (contact_id, name, phone, relation, role)
         * Luồng hoạt động:
         *   1. JOIN contacts với contact_roles theo role.
         *   2. Trả danh sách; [] nếu exception.
         */
        """
        try:
            conn = self._conn()
            rows = conn.cursor().execute("""
                SELECT c.contact_id, c.name, c.phone, c.relation, ? as role
                FROM contacts c
                JOIN contact_roles cr ON c.contact_id = cr.contact_id
                WHERE cr.role = ?
            """, (role, role)).fetchall()
            conn.close()
            return rows
        except Exception as e:
            print("[DATABASE]", e)
            return []

    # ─────────────────────────────────────────
    # SMS PRIORITY LOOKUP
    # ─────────────────────────────────────────

    def get_all_phones(self) -> list:
        """
        /**
         * Chức năng: Lấy tất cả số điện thoại trong danh bạ (mọi vai trò)
         *            — dùng cho SOS gửi đến tất cả người liên hệ.
         * Tham số: Không
         * Trả về: list[str] số điện thoại; [] nếu exception
         * Luồng hoạt động:
         *   1. SELECT DISTINCT phone FROM contacts.
         */
        """
        try:
            conn = self._conn()
            rows = conn.cursor().execute(
                "SELECT DISTINCT phone FROM contacts"
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception as e:
            print("[DATABASE]", e)
            return []

    def get_phones_by_priority(self, priority: int) -> list:
        """
        /**
         * Chức năng: Lấy danh sách SĐT nhận SMS theo mức ưu tiên sự kiện —
         *            P0 gửi rộng nhất, P2/P3 chỉ gửi cho CHĂM SÓC.
         * Tham số:
         *   - priority : 0=tính mạng, 1=khẩn cấp, 2/3=hỗ trợ/nhu cầu
         * Trả về: list[str] số điện thoại
         * Luồng hoạt động:
         *   1. Xác định tập roles theo priority.
         *   2. Gọi _phones_for_roles(roles) và trả kết quả.
         */
        """
        if priority == 0:
            roles = ["ƯU TIÊN", "CHĂM SÓC", "CẦN THIẾT"]
        elif priority == 1:
            roles = ["ƯU TIÊN", "CHĂM SÓC"]
        else:  # 2, 3
            roles = ["CHĂM SÓC"]
        return self._phones_for_roles(roles)

    def get_phones_by_role(self, role: str) -> list:
        """
        /**
         * Chức năng: Lấy danh sách SĐT của tất cả liên hệ có vai trò chỉ định.
         * Tham số:
         *   - role : tên vai trò cần lọc
         * Trả về: list[str] số điện thoại
         * Luồng hoạt động:
         *   1. Gọi _phones_for_roles([role]).
         */
        """
        return self._phones_for_roles([role])

    def _phones_for_roles(self, roles: list) -> list:
        """
        /**
         * Chức năng: Query danh sách SĐT DISTINCT của tất cả liên hệ có
         *            vai trò nằm trong danh sách roles.
         * Tham số:
         *   - roles : list[str] tên vai trò cần lọc
         * Trả về: list[str] số điện thoại; [] nếu roles rỗng hoặc exception
         * Luồng hoạt động:
         *   1. Nếu roles rỗng: trả [].
         *   2. Xây dựng placeholder SQL động và query JOIN.
         *   3. Trả list SĐT DISTINCT.
         */
        """
        if not roles:
            return []
        try:
            placeholders = ",".join("?" * len(roles))
            conn = self._conn()
            rows = conn.cursor().execute(f"""
                SELECT DISTINCT c.phone
                FROM contacts c
                JOIN contact_roles cr ON c.contact_id = cr.contact_id
                WHERE cr.role IN ({placeholders})
            """, roles).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception as e:
            print("[DATABASE]", e)
            return []

    # ─────────────────────────────────────────
    # QUICK MESSAGES
    # ─────────────────────────────────────────

    def load_quick_messages(self) -> dict:
        """
        /**
         * Chức năng: Tải toàn bộ 10 slot tin nhắn nhanh từ database.
         * Tham số: Không
         * Trả về: dict {slot: text} cho slot 1-10; dict rỗng nếu exception
         * Luồng hoạt động:
         *   1. SELECT slot, text FROM quick_messages ORDER BY slot.
         *   2. Chuyển danh sách thành dict và trả về.
         */
        """
        try:
            conn = self._conn()
            rows = conn.cursor().execute(
                "SELECT slot, text FROM quick_messages ORDER BY slot"
            ).fetchall()
            conn.close()
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            print("[DATABASE]", e)
            return {i: "" for i in range(1, 11)}

    def save_quick_message(self, slot: int, text: str) -> bool:
        """
        /**
         * Chức năng: Lưu nội dung văn bản cho một slot tin nhắn nhanh.
         * Tham số:
         *   - slot : số thứ tự slot (1-10)
         *   - text : nội dung văn bản (sẽ được strip)
         * Trả về: True nếu thành công, False nếu slot ngoài phạm vi hoặc exception
         * Luồng hoạt động:
         *   1. Kiểm tra slot trong [1, 10].
         *   2. INSERT OR REPLACE vào quick_messages.
         *   3. Commit và đóng kết nối.
         */
        """
        if slot < 1 or slot > 10:
            return False
        try:
            conn = self._conn()
            conn.cursor().execute(
                "INSERT OR REPLACE INTO quick_messages (slot, text) VALUES (?, ?)",
                (slot, text.strip())
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print("[DATABASE]", e)
            return False

    def get_quick_message(self, slot: int) -> str:
        """
        /**
         * Chức năng: Lấy nội dung văn bản của một slot tin nhắn nhanh.
         * Tham số:
         *   - slot : số thứ tự slot (1-10)
         * Trả về: str nội dung; "" nếu trống hoặc exception
         * Luồng hoạt động:
         *   1. SELECT text FROM quick_messages WHERE slot = ?.
         *   2. Trả row[0] nếu có, "" nếu không.
         */
        """
        try:
            conn = self._conn()
            row = conn.cursor().execute(
                "SELECT text FROM quick_messages WHERE slot = ?", (slot,)
            ).fetchone()
            conn.close()
            return row[0] if row else ""
        except Exception as e:
            print("[DATABASE]", e)
            return ""

    # ─────────────────────────────────────────
    # LOGS
    # ─────────────────────────────────────────

    def add_log(self, message):
        """
        /**
         * Chức năng: Ghi một dòng nhật ký vào bảng logs với timestamp hiện tại
         *            và phát tín hiệu log_updated trên EventBus.
         * Tham số:
         *   - message : nội dung thông điệp cần ghi
         * Trả về: None
         * Luồng hoạt động:
         *   1. INSERT (timestamp, message) vào bảng logs.
         *   2. Commit và phát bus.log_updated (bỏ qua nếu bus chưa sẵn sàng).
         *   3. Đóng kết nối trong finally.
         */
        """
        conn = None
        try:
            conn = self._conn()
            conn.cursor().execute(
                "INSERT INTO logs (timestamp, message) VALUES (?, ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
            )
            conn.commit()
            try:
                from core.event_bus import bus
                bus.log_updated.emit()
            except Exception:
                pass
        except Exception as e:
            print("[LOG ERROR]", e)
        finally:
            if conn:
                conn.close()

    def load_logs(self):
        """
        /**
         * Chức năng: Tải tối đa 500 bản ghi nhật ký gần nhất, sắp xếp mới nhất lên trước.
         * Tham số: Không
         * Trả về: list of tuple (timestamp, message); [] nếu exception
         * Luồng hoạt động:
         *   1. SELECT timestamp, message FROM logs ORDER BY id DESC LIMIT 500.
         *   2. Trả danh sách kết quả.
         */
        """
        try:
            conn = self._conn()
            rows = conn.cursor().execute(
                "SELECT timestamp, message FROM logs ORDER BY id DESC LIMIT 500"
            ).fetchall()
            conn.close()
            return rows
        except Exception as e:
            print("[DATABASE]", e)
            return []

    def clear_logs(self):
        """
        /**
         * Chức năng: Xóa toàn bộ nhật ký trong bảng logs.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. DELETE FROM logs.
         *   2. Commit và đóng kết nối trong finally.
         */
        """
        conn = None
        try:
            conn = self._conn()
            conn.execute("DELETE FROM logs")
            conn.commit()
        except Exception as e:
            print("[DATABASE]", e)
        finally:
            if conn:
                conn.close()


database_service = DatabaseService()
