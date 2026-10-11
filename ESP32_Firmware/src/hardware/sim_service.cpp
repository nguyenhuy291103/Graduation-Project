#include <Arduino.h>

#include "config.h"
#include "system_state.h"
#include "debug.h"

// ============================================
// EXTERNAL
// ============================================

extern HardwareSerial SerialAT;

extern void showLCDMessage(
    const String& line1,
    const String& line2);

extern String buildNewSMSPacket(
    const String& phone,
    const String& message);

extern String buildSMSResultPacket(
    const String& originalPacketId,
    const String& phone,
    const String& status,
    int priority,
    const String& category
);

extern void sendRawPacket(
    const String& packet);

extern void sendTrackedPacket(
    const String& packet,
    const String& packetId);

extern void checkSIMStatus();

extern bool sendingSMS;

extern String buildSMSDeliveryPacket(
    const String& phone,
    const String& status,
    int mr);

// Lưu phản hồi lỗi AT cuối cùng để kiểm tra mã lỗi cụ thể
static String _lastATError = "";

// Forward declaration — định nghĩa đầy đủ sau waitForResponse
static void processNewSMS(const String& response);

/**
 * Chức năng: Trích xuất giá trị packet_id từ chuỗi JSON thô bằng tìm chuỗi
 *            đơn giản, không cần parse JSON.
 * Tham số:
 *   - pkt : chuỗi JSON gói tin đầy đủ
 * Trả về: String packet_id, hoặc "" nếu không tìm thấy
 * Luồng hoạt động:
 *   1. Tìm vị trí "\"packet_id\":\"" trong chuỗi.
 *   2. Cắt chuỗi từ sau dấu " mở đến dấu " đóng kế tiếp.
 */
static String extractPacketId(const String& pkt)
{
    int idx = pkt.indexOf("\"packet_id\":\"");
    if (idx < 0) return "";
    int start = idx + 13;
    int end   = pkt.indexOf("\"", start);
    return (end > start) ? pkt.substring(start, end) : "";
}

// ============================================
// SMS REFERENCE MAP (mr → phone cho +CDS:)
// ============================================

#define MAX_SMS_REFS 10

struct SMSRef
{
    int  mr;
    char phone[16];
    bool valid;
};

static SMSRef smsRefMap[MAX_SMS_REFS];

/**
 * Chức năng: Lưu ánh xạ Message Reference (mr) → số điện thoại vào bảng
 *            smsRefMap để tra cứu khi nhận delivery report +CDS:.
 * Tham số:
 *   - mr    : Message Reference từ +CMGS: sau khi gửi SMS
 *   - phone : số điện thoại đã gửi SMS
 * Trả về: void
 * Luồng hoạt động:
 *   1. Tìm slot trống (valid==false) trong smsRefMap và lưu vào đó.
 *   2. Nếu bảng đầy: ghi đè slot 0 (circular overwrite).
 */
static void storeSMSRef(int mr, const String& phone)
{
    for (int i = 0; i < MAX_SMS_REFS; i++)
    {
        if (!smsRefMap[i].valid)
        {
            smsRefMap[i].mr    = mr;
            smsRefMap[i].valid = true;
            strncpy(smsRefMap[i].phone,
                    phone.c_str(), 15);
            smsRefMap[i].phone[15] = '\0';
            return;
        }
    }
    // Tất cả đầy — ghi đè slot đầu
    smsRefMap[0].mr    = mr;
    smsRefMap[0].valid = true;
    strncpy(smsRefMap[0].phone,
            phone.c_str(), 15);
    smsRefMap[0].phone[15] = '\0';
}

/**
 * Chức năng: Tìm và lấy số điện thoại theo Message Reference từ bảng smsRefMap
 *            (đánh dấu slot là invalid sau khi lấy).
 * Tham số:
 *   - mr : Message Reference cần tra cứu
 * Trả về: String số điện thoại tương ứng, hoặc "" nếu không tìm thấy
 * Luồng hoạt động:
 *   1. Duyệt smsRefMap tìm slot có valid==true và mr khớp.
 *   2. Đánh dấu slot.valid = false (consume once) và trả về phone.
 *   3. Trả "" nếu không tìm thấy.
 */
static String lookupSMSRef(int mr)
{
    for (int i = 0; i < MAX_SMS_REFS; i++)
    {
        if (smsRefMap[i].valid &&
            smsRefMap[i].mr == mr)
        {
            String p = smsRefMap[i].phone;
            smsRefMap[i].valid = false;
            return p;
        }
    }
    return "";
}

/**
 * Chức năng: Lấy mutex simMutex với timeout để truy cập độc quyền module SIM.
 * Tham số:
 *   - timeout : thời gian chờ tối đa (mặc định 5000ms)
 * Trả về: true nếu lấy được mutex, false nếu timeout hoặc mutex NULL
 * Luồng hoạt động:
 *   1. Kiểm tra simMutex != NULL.
 *   2. Gọi xSemaphoreTake với timeout và trả kết quả.
 */
bool lockSIM(
    TickType_t timeout =
    pdMS_TO_TICKS(5000))
{
    if (simMutex == NULL)
    {
        return false;
    }

    return
        xSemaphoreTake(
            simMutex,
            timeout)
        == pdTRUE;
}

/**
 * Chức năng: Giải phóng mutex simMutex sau khi hoàn thành thao tác SIM.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Kiểm tra simMutex != NULL rồi gọi xSemaphoreGive.
 */
void unlockSIM()
{
    if (simMutex != NULL)
    {
        xSemaphoreGive(
            simMutex);
    }
}

// ============================================
// UTF-8 TO UCS2 HEX (for Vietnamese SMS)
// ============================================

/**
 * Chức năng: Chuyển chuỗi UTF-8 sang chuỗi hex UCS2 (Big Endian) để gửi SMS
 *            Unicode (tiếng Việt) qua AT+CMGS ở chế độ UCS2.
 * Tham số:
 *   - utf8 : chuỗi văn bản UTF-8 đầu vào
 * Trả về: String chuỗi hex UCS2 (mỗi codepoint 4 ký tự hex)
 * Luồng hoạt động:
 *   1. Duyệt từng byte trong utf8, decode thành Unicode codepoint.
 *      - 1 byte (0xxxxxxx): ASCII.
 *      - 2 byte (110xxxxx 10xxxxxx): U+0080..U+07FF.
 *      - 3 byte (1110xxxx ...): U+0800..U+FFFF.
 *   2. Định dạng mỗi codepoint thành "%04X" và nối vào result.
 */
static String utf8ToUCS2Hex(const String& utf8)
{
    String result = "";
    const uint8_t* bytes = (const uint8_t*)utf8.c_str();
    int len = (int)utf8.length();
    int i = 0;

    while (i < len)
    {
        uint16_t cp = 0;
        uint8_t b = bytes[i];

        if ((b & 0x80) == 0)
        {
            cp = b;
            i += 1;
        }
        else if ((b & 0xE0) == 0xC0 && i + 1 < len)
        {
            cp = ((uint16_t)(b & 0x1F) << 6) |
                 (uint16_t)(bytes[i + 1] & 0x3F);
            i += 2;
        }
        else if ((b & 0xF0) == 0xE0 && i + 2 < len)
        {
            cp = ((uint16_t)(b & 0x0F) << 12) |
                 ((uint16_t)(bytes[i + 1] & 0x3F) << 6) |
                 (uint16_t)(bytes[i + 2] & 0x3F);
            i += 3;
        }
        else
        {
            i += 1;
            continue;
        }

        char buf[5];
        sprintf(buf, "%04X", (unsigned int)cp);
        result += buf;
    }

    return result;
}

/**
 * Chức năng: Chuyển chuỗi ASCII thành hex UCS2 — dùng để encode số điện
 *            thoại khi gửi AT+CMGS ở chế độ UCS2.
 * Tham số:
 *   - text : chuỗi ASCII đầu vào
 * Trả về: String chuỗi hex UCS2
 * Luồng hoạt động:
 *   1. Với mỗi ký tự ASCII, định dạng giá trị byte thành "%04X".
 *   2. Nối các kết quả thành chuỗi trả về.
 */
static String asciiToUCS2Hex(
    const String& text)
{
    String result;

    for (int i = 0; i < text.length(); i++)
    {
        char buf[5];

        sprintf(
            buf,
            "%04X",
            (uint8_t)text[i]
        );

        result += buf;
    }

    return result;
}

// ============================================
// UCS2 HEX → UTF-8 (for incoming SMS decode)
// ============================================

/**
 * Chức năng: Chuyển chuỗi hex UCS2 (nhận từ modem) thành UTF-8 để hiển thị
 *            và xử lý tin nhắn tiếng Việt nhận về.
 * Tham số:
 *   - ucs2hex : chuỗi hex UCS2 (mỗi codepoint 4 ký tự)
 * Trả về: String chuỗi UTF-8
 * Luồng hoạt động:
 *   1. Đọc từng nhóm 4 ký tự hex, parse thành codepoint uint16_t.
 *   2. Encode codepoint thành UTF-8 (1-3 bytes tuỳ dải giá trị).
 *   3. Nối tất cả vào result và trả về.
 */
static String ucs2HexToUtf8(const String& ucs2hex)
{
    String result = "";
    int len = (int)ucs2hex.length();

    for (int i = 0; i + 3 < len; i += 4)
    {
        char buf[5] = {
            ucs2hex[i], ucs2hex[i+1],
            ucs2hex[i+2], ucs2hex[i+3], '\0'
        };
        uint16_t cp = (uint16_t)strtoul(buf, nullptr, 16);

        if (cp < 0x80)
        {
            result += (char)cp;
        }
        else if (cp < 0x800)
        {
            result += (char)(0xC0 | (cp >> 6));
            result += (char)(0x80 | (cp & 0x3F));
        }
        else
        {
            result += (char)(0xE0 | (cp >> 12));
            result += (char)(0x80 | ((cp >> 6) & 0x3F));
            result += (char)(0x80 | (cp & 0x3F));
        }
    }
    return result;
}

// ============================================
// UTF-8 UNICODE CHAR HELPERS
// ============================================

/**
 * Chức năng: Đếm số ký tự Unicode (codepoint) trong chuỗi UTF-8 để kiểm tra
 *            giới hạn 70 ký tự của một SMS UCS2 đơn.
 * Tham số:
 *   - utf8 : chuỗi UTF-8 cần đếm
 * Trả về: int số codepoint Unicode
 * Luồng hoạt động:
 *   1. Duyệt byte array, nhảy theo độ dài byte sequence của từng codepoint.
 *   2. Tăng count mỗi lần nhảy, trả về count khi hết chuỗi.
 */
static int countUnicodeChars(const String& utf8)
{
    const uint8_t* bytes = (const uint8_t*)utf8.c_str();
    int len = (int)utf8.length();
    int count = 0;
    int i = 0;
    while (i < len)
    {
        uint8_t b = bytes[i];
        if      ((b & 0x80) == 0x00) i += 1;
        else if ((b & 0xE0) == 0xC0) i += 2;
        else if ((b & 0xF0) == 0xE0) i += 3;
        else if ((b & 0xF8) == 0xF0) i += 4;
        else                          i += 1;
        count++;
    }
    return count;
}

/**
 * Chức năng: Cắt chuỗi UTF-8 tại maxChars ký tự Unicode và thêm "..." nếu
 *            chuỗi gốc dài hơn — đảm bảo không cắt giữa byte sequence.
 * Tham số:
 *   - utf8     : chuỗi UTF-8 gốc
 *   - maxChars : số ký tự Unicode tối đa
 * Trả về: String chuỗi đã cắt (hoặc nguyên gốc nếu đủ ngắn)
 * Luồng hoạt động:
 *   1. Duyệt byte array, đếm codepoint đến maxChars rồi ghi nhớ vị trí byte i.
 *   2. Nếu i < len: cắt tại i và nối "...".
 *   3. Ngược lại trả chuỗi gốc.
 */
static String truncateUTF8(const String& utf8, int maxChars)
{
    const uint8_t* bytes = (const uint8_t*)utf8.c_str();
    int len = (int)utf8.length();
    int count = 0;
    int i = 0;
    while (i < len && count < maxChars)
    {
        uint8_t b = bytes[i];
        if      ((b & 0x80) == 0x00) i += 1;
        else if ((b & 0xE0) == 0xC0) i += 2;
        else if ((b & 0xF0) == 0xE0) i += 3;
        else if ((b & 0xF8) == 0xF0) i += 4;
        else                          i += 1;
        count++;
    }
    if (i < len)
    {
        return utf8.substring(0, i) + "...";
    }
    return utf8;
}

// ============================================
// INIT SIM
// ============================================

/**
 * Chức năng: Khởi tạo module SIM GSM — mở cổng SerialAT, gửi lệnh AT cơ
 *            bản và đặt lại trạng thái hệ thống về chưa sẵn sàng.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Mở SerialAT (GPIO 16/17) ở SIM_BAUD_RATE.
 *   2. Gửi AT để đánh thức module; drain buffer thừa.
 *   3. Gửi AT, AT+CMGF=1 (text mode), AT+CSCS="GSM", AT+CNMI=1,2,0,1,0.
 *   4. Đặt simReady/simInserted/networkReady/smsReady = false.
 *   5. Hiện "SIM INIT / CHECKING..." trên LCD.
 */
void initSIM()
{
    SerialAT.begin(
        SIM_BAUD_RATE,
        SERIAL_8N1,
        16,
        17);

    SerialAT.println("AT");

    delay(1000);

    while (SerialAT.available())
    {
        Serial.write(
            SerialAT.read());
    }
    delay(3000);

    DEBUG_PRINTLN("[SIM] Initializing...");

    SerialAT.println("AT");

    delay(1000);

    SerialAT.println("AT+CMGF=1");

    delay(1000);

    SerialAT.println("AT+CSCS=\"GSM\"");

    delay(1000);

    SerialAT.println("AT+CNMI=1,2,0,1,0");

    delay(1000);

    systemState.simReady = false;

    systemState.simInserted = false;

    systemState.networkReady = false;

    systemState.smsReady = false;

    showLCDMessage(
        "SIM INIT",
        "CHECKING...");
}

// ============================================
// SIGNAL CHECK
// ============================================

/**
 * Chức năng: Kiểm tra cường độ tín hiệu GSM qua AT+CSQ và cập nhật
 *            systemState.signalStrength; cảnh báo LCD nếu tín hiệu yếu.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Gửi AT+CSQ và đọc phản hồi.
 *   2. Nếu phản hồi có +CMT: xử lý SMS đến ngay.
 *   3. Parse giá trị từ "+CSQ: <rssi>,..." và lưu vào signalStrength.
 *   4. Nếu tín hiệu <= 5 và không đang nhập liệu: hiện cảnh báo LCD.
 */
static void checkSignalInternal()
{
    SerialAT.println("AT+CSQ");

    delay(500);

    String response = "";

    while (SerialAT.available())
    {
        response += (char)SerialAT.read();
    }

    if (response.indexOf("+CMT:") >= 0)
        processNewSMS(response);

    int index = response.indexOf("+CSQ:");

    if (index >= 0)
    {
        int commaIndex =
            response.indexOf(",", index);

        String signal =
            response.substring(
                index + 6,
                commaIndex);

        systemState.signalStrength =
            signal.toInt();

        if (
            systemState.inputState ==
            INPUT_IDLE
        )
        {
            if (systemState.signalStrength <= 5)
            {
                showLCDMessage(
                    "LOW SIGNAL",
                    String(systemState.signalStrength));
            }
        }
    }
}

// ============================================
// WAIT RESPONSE
// ============================================

/**
 * Chức năng: Chờ phản hồi từ module SIM có chứa chuỗi expected trong vòng
 *            timeout ms; hỗ trợ capture toàn bộ phản hồi qua outResponse.
 * Tham số:
 *   - expected    : chuỗi cần tìm trong phản hồi (ví dụ "OK", ">", "+CMGS:")
 *   - timeout     : thời gian chờ tối đa (ms)
 *   - outResponse : con trỏ String nhận toàn bộ phản hồi (có thể NULL)
 * Trả về: true nếu tìm thấy expected, false nếu timeout hoặc gặp ERROR
 * Luồng hoạt động:
 *   1. Vòng lặp đọc SerialAT và tích lũy vào response cho đến khi timeout.
 *   2. Trả true nếu response chứa expected.
 *   3. Trả false ngay nếu response chứa ERROR/+CMS ERROR/+CME ERROR.
 *   4. Trả false khi timeout.
 */
bool waitForResponse(
    const String& expected,
    unsigned long timeout,
    String* outResponse)
{
    unsigned long startTime = millis();

    String response = "";

    while (millis() - startTime < timeout)
    {
        while (SerialAT.available())
        {
            response +=
                (char)SerialAT.read();
        }

        // SUCCESS
        if (response.indexOf(expected) >= 0)
        {
            DEBUG_PRINTLN("");
            DEBUG_PRINTLN("===== SIM RESPONSE =====");
            DEBUG_PRINTLN(response);
            DEBUG_PRINTLN("========================");

            if (outResponse != nullptr)
                *outResponse = response;

            return true;
        }

        // COMMON ERRORS
        if (response.indexOf("ERROR") >= 0 ||
            response.indexOf("+CMS ERROR") >= 0 ||
            response.indexOf("+CME ERROR") >= 0)
        {
            _lastATError = response;

            DEBUG_PRINTLN("");
            DEBUG_PRINTLN("===== SIM ERROR =====");
            DEBUG_PRINTLN(response);
            DEBUG_PRINTLN("=====================");

            if (outResponse != nullptr)
                *outResponse = response;

            return false;
        }

        delay(10);
    }

    DEBUG_PRINTLN("");
    DEBUG_PRINTLN("===== SIM TIMEOUT =====");
    DEBUG_PRINTLN(response);
    DEBUG_PRINTLN("=======================");

    if (outResponse != nullptr)
        *outResponse = response;

    return false;
}

// Overload không cần capture response (gọi từ checkSIMStatus, v.v.)
static bool waitForResponse(
    const String& expected,
    unsigned long timeout)
{
    return waitForResponse(expected, timeout, nullptr);
}


// ============================================
// PROCESS INCOMING +CMT: (helper dùng chung)
// Gọi được từ handleSIMIncoming() và sendSMS()
// ============================================

/**
 * Chức năng: Xử lý SMS đến (+CMT:) từ buffer phản hồi AT — decode nội dung,
 *            cập nhật state và gửi gói NEW_SMS lên Python qua UART.
 * Tham số:
 *   - response : chuỗi phản hồi AT thô chứa +CMT: và nội dung SMS
 * Trả về: void
 * Luồng hoạt động:
 *   1. Trích số điện thoại người gửi từ dấu ngoặc kép đầu tiên.
 *   2. Lấy dòng cuối cùng làm nội dung SMS (body).
 *   3. Nếu body là hex UCS2 (chỉ 0-9 A-F, dài bội 4): decode sang UTF-8.
 *   4. Cập nhật systemState.lastSMSPhone/Message.
 *   5. Hiện "NEW SMS / <tên hoặc SĐT>" trên LCD.
 *   6. Xây dựng và gửi gói NEW_SMS qua sendTrackedPacket.
 */
static void processNewSMS(const String& response)
{
    String phone = "UNKNOWN";

    int firstQuote  = response.indexOf("\"");
    int secondQuote = response.indexOf("\"", firstQuote + 1);
    if (firstQuote >= 0 && secondQuote >= 0)
        phone = response.substring(firstQuote + 1, secondQuote);

    // Trim bản sao để lastIndexOf tìm đúng \n phân cách header/body
    String trimmedResp = response;
    trimmedResp.trim();
    int lastLine = trimmedResp.lastIndexOf("\n");
    String message = (lastLine >= 0)
        ? trimmedResp.substring(lastLine + 1)
        : trimmedResp;
    message.trim();

    // UCS2 detection: chỉ chấp nhận hex CHỮ HOA (modem luôn gửi uppercase)
    // và tối thiểu 8 ký tự (2 codepoint) để tránh nhầm text ASCII như "CAFE"
    bool isUCS2Hex = (message.length() >= 8) &&
                     (message.length() % 4 == 0);
    if (isUCS2Hex)
    {
        for (int j = 0; j < (int)message.length() && isUCS2Hex; j++)
        {
            char c = message[j];
            if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F')))
                isUCS2Hex = false;
        }
    }
    if (isUCS2Hex)
        message = ucs2HexToUtf8(message);

    systemState.lastSMSPhone   = phone;
    systemState.lastSMSMessage = message;

    extern String findNameByPhone(const String& phone);
    String senderLabel = findNameByPhone(phone);
    if (senderLabel.length() == 0) senderLabel = phone;

    showLCDMessage("NEW SMS", senderLabel);

    String packet = buildNewSMSPacket(phone, message);
    sendTrackedPacket(packet, extractPacketId(packet));

    DEBUG_PRINT("[CMT] phone=");
    DEBUG_PRINT(phone);
    DEBUG_PRINT(" msg=");
    DEBUG_PRINTLN(message);
}

// ============================================
// SEND SMS
// ============================================

/**
 * Chức năng: Gửi SMS qua module SIM ở chế độ UCS2 (hỗ trợ tiếng Việt) với
 *            delivery report request; báo kết quả thành công/thất bại lên Python.
 * Tham số:
 *   - packetId : ID gói SEND_SMS gốc từ Python (để gửi lại trong SMS_RESULT)
 *   - phone    : số điện thoại người nhận
 *   - message  : nội dung tin nhắn UTF-8
 *   - priority : mức ưu tiên (0-3)
 *   - category : danh mục cảnh báo
 * Trả về: void
 * Luồng hoạt động:
 *   1. Kiểm tra simReady/simInserted/networkReady/smsReady; gửi FAILED nếu chưa sẵn sàng.
 *   2. Lấy simMutex; gửi FAILED nếu không lấy được.
 *   3. Bật chế độ text (AT+CMGF=1) và UCS2 (AT+CSCS="UCS2").
 *   4. Bật delivery report (AT+CSMP=49,167,2,25).
 *   5. Gửi AT+CMGS="<phoneUCS2>" và chờ prompt ">".
 *   6. Encode message thành UCS2 hex, gửi và kết thúc bằng CTRL+Z.
 *   7. Chờ +CMGS: (15s): lưu MR, gửi SMS_RESULT SUCCESS.
 *   8. Nếu timeout/error: gửi SMS_RESULT FAILED.
 *   9. Xử lý +CMT: nhận được trong lúc chờ; reset charset về GSM; giải phóng mutex.
 */
void sendSMS(
    const String& packetId,
    const String& phone,
    const String& message,
    int priority,
    const String& category
)
{
    DEBUG_PRINTLN("====================");

    DEBUG_PRINTLN("[SMS REQUEST]");

    DEBUG_PRINT("Packet ID: ");

    DEBUG_PRINTLN(packetId);

    DEBUG_PRINT("Phone: ");

    DEBUG_PRINTLN(phone);

    DEBUG_PRINT("Message: ");

    DEBUG_PRINTLN(message);

    DEBUG_PRINT("[SMS] simReady = ");
    DEBUG_PRINTLN(systemState.simReady);

    DEBUG_PRINT("[SMS] simInserted = ");
    DEBUG_PRINTLN(systemState.simInserted);

    DEBUG_PRINT("[SMS] networkReady = ");
    DEBUG_PRINTLN(systemState.networkReady);

    DEBUG_PRINT("[SMS] smsReady = ");
    DEBUG_PRINTLN(systemState.smsReady);
    if(!lockSIM())
    {
        DEBUG_PRINTLN(
            "[SMS] LOCK FAIL");

        String packet =
            buildSMSResultPacket(
                packetId,
                phone,
                "FAILED",
                priority,
                category
            );

        sendRawPacket(
            packet
        );

        return;
    }

    DEBUG_PRINTLN(
        "[SMS] Mutex OK");
    // ========================================
    // CHECK SYSTEM
    // ========================================
    if (!systemState.simReady)
    {
        DEBUG_PRINTLN(
            "[SMS] STOP : simReady = false");
        showLCDMessage(
            "SMS FAILED",
            "SIM ERROR");

        String packet =
            buildSMSResultPacket(
                packetId,
                phone,
                "FAILED",
                priority,
                category
            );

        sendRawPacket(
            packet
        );
        unlockSIM();
        return;
    }

    if (!systemState.simInserted)
    {
        DEBUG_PRINTLN(
            "[SMS] STOP : simInserted = false");
        showLCDMessage(
            "SMS FAILED",
            "NO SIM");

        String packet =
            buildSMSResultPacket(
                packetId,
                phone,
                "FAILED",
                priority,
                category
            );

        sendRawPacket(
            packet
        );
        unlockSIM();
        return;
    }

    if (!systemState.networkReady)
    {
        DEBUG_PRINTLN(
            "[SMS] STOP : networkReady = false");
        showLCDMessage(
            "SMS FAILED",
            "NO SIGNAL");

        String packet =
            buildSMSResultPacket(
                packetId,
                phone,
                "FAILED",
                priority,
                category
            );

        sendRawPacket(
            packet
        );
        unlockSIM();
        return;
    }

    if (!systemState.smsReady)
    {
        DEBUG_PRINTLN(
            "[SMS] STOP : smsReady = false");
        showLCDMessage(
            "SMS FAILED",
            "SMS MODE");

        String packet =
            buildSMSResultPacket(
                packetId,
                phone,
                "FAILED",
                priority,
                category
            );

        sendRawPacket(
            packet
        );
        unlockSIM();
        return;
    }


    // ========================================
    // LCD
    // ========================================
    sendingSMS = true;
    showLCDMessage(
        "SENDING SMS",
        phone);

    // ========================================
    // SMS TEXT MODE
    // ========================================

    SerialAT.println("AT+CMGF=1");

    if (!waitForResponse("OK", 2000))
    {
        Serial.println("[SMS] CMGF FAIL");

        unlockSIM();
        return;
    }

    // ========================================
    // UCS2 CHARSET
    // ========================================

    SerialAT.println("AT+CSCS=\"UCS2\"");

    bool ucs2Ready =
        waitForResponse("OK", 2000);

    if (!ucs2Ready)
    {
        Serial.println(
            "[SMS] UCS2 NOT SUPPORTED");

        unlockSIM();
        return;
    }

    // ========================================
    // UNICODE SMS
    // ========================================

    // fo=49 (0x31): SRR=1 bật delivery report request
    SerialAT.println(
        "AT+CSMP=49,167,2,25"
    );

    if (!waitForResponse("OK", 2000))
    {
        Serial.println(
            "[SMS] CSMP FAIL");

        unlockSIM();
        return;
    }
    while (SerialAT.available())
    {
        SerialAT.read();
    }

    // ========================================
    // START SMS
    // ========================================

    String phoneUCS2 =
    asciiToUCS2Hex(phone);

    Serial.print(
        "[SMS] UCS2 PHONE = ");

    Serial.println(
        phoneUCS2);

    SerialAT.print(
        "AT+CMGS=\"");

    SerialAT.print(
        phoneUCS2);

    SerialAT.println(
        "\"");

    Serial.println(
        "[SMS] WAITING FOR > PROMPT");

    if (!waitForResponse(">", 5000))
    {
        SerialAT.println("AT+CSCS=\"GSM\"");
        delay(300);

        showLCDMessage(
            "SMS FAILED",
            "CMGS ERROR");

        String packet =
            buildSMSResultPacket(
                packetId,
                phone,
                "FAILED",
                priority,
                category
            );

        sendRawPacket(
            packet
        );
        unlockSIM();
        return;
    }

    // ========================================
    // SEND MESSAGE
    // ========================================

    // UCS2 TEXT mode: max 70 Unicode chars per segment.
    // Truncate to 67 + "..." (3 chars) so total <= 70.
    String msgToSend = (countUnicodeChars(message) > 70)
        ? truncateUTF8(message, 67)
        : message;

    if (ucs2Ready)
    {
        SerialAT.print(utf8ToUCS2Hex(msgToSend));
    }
    else
    {
        // Fallback: strip non-ASCII bytes so at least ASCII text goes through
        String ascii = "";
        for (int i = 0; i < (int)msgToSend.length(); i++)
        {
            if ((uint8_t)msgToSend[i] < 0x80) ascii += msgToSend[i];
        }
        SerialAT.print(ascii);
    }

    delay(200);

    // CTRL + Z
    SerialAT.write(26);

    // ========================================
    // WAIT RESULT
    // ========================================

    String cmgsResponse;
    if (waitForResponse("+CMGS:", 15000, &cmgsResponse))
    {
        sendingSMS = false;

        // Lấy message reference (mr) từ "+CMGS: <mr>"
        int cmgsPos = cmgsResponse.indexOf("+CMGS:");
        if (cmgsPos >= 0)
        {
            String mrStr =
                cmgsResponse.substring(cmgsPos + 6);
            mrStr.trim();
            int mr = mrStr.toInt();
            storeSMSRef(mr, phone);
            DEBUG_PRINT("[SMS] MR = ");
            DEBUG_PRINTLN(mr);
        }

        DEBUG_PRINT("[SMS SUCCESS] ");

        DEBUG_PRINTLN(packetId);
        showLCDMessage(
            "SMS SENT",
            phone);

        String packet =
            buildSMSResultPacket(
                packetId,
                phone,
                "SUCCESS",
                priority,
                category
            );

        sendRawPacket(
            packet
        );

        DEBUG_PRINTLN("[SIM] SMS SENT SUCCESS");
    }
    else
    {
        sendingSMS = false;

        DEBUG_PRINT("[SMS FAILED] ");
        DEBUG_PRINTLN(packetId);

        String packet =
            buildSMSResultPacket(
                packetId,
                phone,
                "FAILED",
                priority,
                category
            );

        sendRawPacket(packet);

        // CMS ERROR: 42 = no credit / insufficient funds
        if (_lastATError.indexOf("+CMS ERROR: 42") >= 0 ||
            _lastATError.indexOf("+CMS ERROR:42")  >= 0)
        {
            showLCDMessage("NO CREDIT", "RELOAD SIM");
            Serial.println("[SMS] NO CREDIT — SIM het tien");
        }
        else
        {
            showLCDMessage("SMS FAILED", "SEND ERROR");
        }

        _lastATError = "";
        DEBUG_PRINTLN("[SIM] SMS SEND FAILED");
    }

    // Nếu +CMT: đến trong lúc chờ CMGS (15s) → xử lý ngay
    if (cmgsResponse.indexOf("+CMT:") >= 0)
    {
        processNewSMS(cmgsResponse);
    }

    // Reset charset back to GSM after sending
    SerialAT.println("AT+CSCS=\"GSM\"");
    delay(300);

    unlockSIM();

}

// ============================================
// HANDLE INCOMING SMS
// ============================================

/**
 * Chức năng: Đọc và xử lý dữ liệu đến từ module SIM (SMS mới, delivery report)
 *            khi không có SMS đang gửi — dùng timeout read thay vì readString().
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Thử lấy simMutex không chặn (timeout=0); bỏ qua nếu không được.
 *   2. Đọc dữ liệu SerialAT với timeout rolling 200ms (không block 1s).
 *   3. Nếu có +CMT:: gọi processNewSMS().
 *   4. Nếu có +CDS:: parse mr và st, tra cứu phone, gửi SMS_DELIVERY packet.
 *   5. Giải phóng simMutex.
 */
void handleSIMIncoming()
{
    if (simMutex == NULL)
    {
        return;
    }

    if (xSemaphoreTake(simMutex, 0) != pdTRUE)
    {
        return;
    }

    if (!SerialAT.available())
    {
        xSemaphoreGive(simMutex);

        return;
    }

    // Đọc từng byte với timeout 200ms thay vì readString() block 1s
    String response = "";
    unsigned long startMs = millis();
    while (millis() - startMs < 200)
    {
        while (SerialAT.available())
        {
            response += (char)SerialAT.read();
            startMs = millis();
        }
        vTaskDelay(5 / portTICK_PERIOD_MS);
    }

    DEBUG_PRINTLN(response);

    // ========================================
    // NEW SMS
    // ========================================

    if (response.indexOf("+CMT:") >= 0)
    {
        processNewSMS(response);
    }

    // ========================================
    // DELIVERY REPORT (+CDS:)
    // ========================================

    if (response.indexOf("+CDS:") >= 0)
    {
        int cdsIdx = response.indexOf("+CDS:");
        String cdsLine =
            response.substring(cdsIdx + 5);
        cdsLine.trim();

        // Format: fo,mr,[ra],[tora],scts,dt,st
        // Lấy mr = token thứ 2 (sau dấu phẩy đầu tiên)
        int c1 = cdsLine.indexOf(",");
        int c2 = (c1 >= 0)
            ? cdsLine.indexOf(",", c1 + 1)
            : -1;
        int mr = -1;
        if (c1 >= 0 && c2 >= 0)
        {
            mr = cdsLine.substring(
                c1 + 1, c2).toInt();
        }

        // Lấy st = token cuối cùng
        // Timestamp trong ngoặc kép có thể chứa dấu phẩy
        // → tìm dấu " cuối cùng rồi lấy token sau đó
        int st = -1;
        int lastQuote = cdsLine.lastIndexOf("\"");
        if (lastQuote >= 0 &&
            lastQuote + 2 < (int)cdsLine.length())
        {
            st = cdsLine.substring(
                lastQuote + 2).toInt();
        }
        else
        {
            int lastComma = cdsLine.lastIndexOf(",");
            if (lastComma >= 0)
            {
                st = cdsLine.substring(
                    lastComma + 1).toInt();
            }
        }

        DEBUG_PRINT("[CDS] mr=");
        DEBUG_PRINT(mr);
        DEBUG_PRINT(" st=");
        DEBUG_PRINTLN(st);

        if (mr >= 0)
        {
            String refPhone = lookupSMSRef(mr);

            // st=0: đã giao; 1-31: đang thử lại;
            // 32-63: lỗi tạm thời; 64+: lỗi vĩnh viễn
            String deliveryStatus =
                (st == 0) ? "DELIVERED" : "FAILED";

            String delivPkt =
                buildSMSDeliveryPacket(
                    refPhone,
                    deliveryStatus,
                    mr);

            sendRawPacket(delivPkt);

            DEBUG_PRINT("[CDS] DELIVERY ");
            DEBUG_PRINT(deliveryStatus);
            DEBUG_PRINT(" phone=");
            DEBUG_PRINTLN(refPhone);
        }
    }

    xSemaphoreGive(simMutex);
}

// ============================================
// CHECK SIM STATUS
// ============================================

/**
 * Chức năng: Kiểm tra tuần tự toàn bộ trạng thái module SIM (module, SIM card,
 *            mạng, SMS mode, tín hiệu) và cập nhật systemState tương ứng.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Bỏ qua nếu đang gửi SMS hoặc không lấy được mutex.
 *   2. AT → kiểm tra simReady; trả về nếu module không phản hồi.
 *   3. AT+CPIN? → kiểm tra simInserted; trả về nếu không có SIM.
 *   4. AT+CREG? → kiểm tra networkReady (0,1 hoặc 0,5); trả về nếu chưa đăng ký.
 *   5. AT+CMGF? → kiểm tra smsReady (+CMGF: 1); trả về nếu không đúng mode.
 *   6. checkSignalInternal() → cập nhật signalStrength.
 *   7. Nếu tất cả sẵn sàng và không đang nhập liệu: hiện "SIM READY / SYSTEM OK".
 *   8. Giải phóng mutex.
 */
void checkSIMStatus()
{
    DEBUG_PRINTLN(
        "[SIM] checkSIMStatus ENTER");

    if(sendingSMS)
    {
        DEBUG_PRINTLN(
            "[SIM] SMS BUSY"
        );

        return;
    }

    if(!lockSIM())
    {
        DEBUG_PRINTLN(
            "[SIM] LOCK FAIL");

        return;
    }

    DEBUG_PRINTLN(
        "[SIM] LOCK OK");
    // ========================================
    // CHECK MODULE
    // ========================================

    DEBUG_PRINTLN(
        "[SIM] SEND AT");

    SerialAT.println("AT");

    delay(1000);

    DEBUG_PRINTLN(
        "[SIM] READ AT RESPONSE");

    String response = "";

    while (SerialAT.available())
    {
        response += (char)SerialAT.read();
    }
    DEBUG_PRINT(
        "[SIM] RESPONSE = ");

    DEBUG_PRINTLN(
        response);
    if (response.indexOf("+CMT:") >= 0)
        processNewSMS(response);
    if (response.indexOf("OK") >= 0)
    {
        systemState.simReady = true;
    }
    else
    {
        systemState.simReady = false;

        showLCDMessage(
            "SIM ERROR",
            "MODULE FAIL");

        unlockSIM();
        return;
    }

    // ========================================
    // CHECK SIM INSERTED
    // ========================================

    SerialAT.println("AT+CPIN?");

    delay(1000);

    response = "";

    while (SerialAT.available())
    {
        response += (char)SerialAT.read();
    }

    if (response.indexOf("+CMT:") >= 0)
        processNewSMS(response);
    if (response.indexOf("READY") >= 0)
    {
        systemState.simInserted = true;
    }
    else
    {
        systemState.simInserted = false;

        showLCDMessage(
            "NO SIM",
            "INSERT SIM");

        unlockSIM();
        return;
    }

    // ========================================
    // CHECK NETWORK
    // ========================================

    SerialAT.println("AT+CREG?");

    delay(1000);

    response = "";

    while (SerialAT.available())
    {
        response += (char)SerialAT.read();
    }

    if (response.indexOf("+CMT:") >= 0)
        processNewSMS(response);
    if (response.indexOf("0,1") >= 0 ||
        response.indexOf("0,5") >= 0)
    {
        systemState.networkReady = true;
    }
    else
    {
        systemState.networkReady = false;

        showLCDMessage(
            "NO NETWORK",
            "CHECK SIGNAL");

        unlockSIM();
        return;
    }

    // ========================================
    // CHECK SMS MODE
    // ========================================

    SerialAT.println("AT+CMGF?");

    delay(1000);

    response = "";

    while (SerialAT.available())
    {
        response += (char)SerialAT.read();
    }

    if (response.indexOf("+CMT:") >= 0)
        processNewSMS(response);
    if (response.indexOf("+CMGF: 1") >= 0)
    {
        systemState.smsReady = true;
    }
    else
    {
        systemState.smsReady = false;

        showLCDMessage(
            "SMS ERROR",
            "TEXT MODE");

        unlockSIM();
        return;
    }

    // ========================================
    // CHECK SIGNAL
    // ========================================

    checkSignalInternal();

    // ========================================
    // READY
    // ========================================

    if (
        systemState.inputState ==
        INPUT_IDLE
    )
    {
        if (systemState.simReady &&
            systemState.simInserted &&
            systemState.smsReady &&
            systemState.networkReady)
        {
            showLCDMessage(
                "SIM READY",
                "SYSTEM OK");
        }
    }

    unlockSIM();
}
