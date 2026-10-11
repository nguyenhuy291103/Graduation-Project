#include <Arduino.h>
#include <ArduinoJson.h>

#include "packet.h"
#include "config.h"
#include "system_state.h"

static unsigned long packetCounter = 0;

/**
 * Chức năng: Tạo ID gói tin duy nhất theo định dạng "PREFIX_XXXXXX"
 *            với số thứ tự tăng dần toàn cục.
 * Tham số:
 *   - prefix : tiền tố định danh loại gói (ví dụ "HB", "SOS", "SYS")
 * Trả về: String ID duy nhất định dạng "PREFIX_000001"
 * Luồng hoạt động:
 *   1. Tăng packetCounter.
 *   2. Định dạng chuỗi theo sprintf "%s_%06lu".
 *   3. Trả về String kết quả.
 */
String generatePacketId(
    const String& prefix)
{
    packetCounter++;

    char buffer[32];

    sprintf(
        buffer,
        "%s_%06lu",
        prefix.c_str(),
        packetCounter);

    return String(buffer);
}

// ============================================
// BUILD CONTACT PACKET
// ============================================

/**
 * Chức năng: Xây dựng gói REQUEST ADD_CONTACT gửi từ ESP32 lên Python
 *            khi người dùng nhập liên hệ mới qua keypad.
 * Tham số:
 *   - contactId : ID liên hệ người dùng nhập
 *   - phone     : số điện thoại người dùng nhập
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type REQUEST, command ADD_CONTACT.
 *   2. Thêm payload {id, phone}.
 *   3. Serialize và trả String.
 */
String buildAddContactPacket(
    const String& contactId,
    const String& phone)
{
    DynamicJsonDocument doc(512);

    doc["type"] = PACKET_REQUEST;
    doc["command"] = CMD_ADD_CONTACT;
    doc["packet_id"] =
        generatePacketId("CONTACT");
    doc["source"] =
        "ESP32";

    doc["target"] =
        "AI_UI";

    doc["timestamp"] =
        millis();

    JsonObject payload =
        doc.createNestedObject("payload");

    payload["id"] = contactId;
    payload["phone"] = phone;

    String output;

    serializeJson(doc, output);

    return output;
}

/**
 * Chức năng: Xây dựng gói EVENT SMS_RESULT thông báo kết quả gửi SMS
 *            về cho Python sau khi module SIM xử lý xong.
 * Tham số:
 *   - originalPacketId : packet_id của lệnh SEND_SMS gốc
 *   - phone            : số điện thoại đã gửi SMS
 *   - status           : "SUCCESS" hoặc "FAILED"
 *   - priority         : mức ưu tiên của SMS (0-3)
 *   - category         : danh mục cảnh báo
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type EVENT, command SMS_RESULT.
 *   2. Dùng lại originalPacketId để Python khớp với lệnh gốc.
 *   3. Thêm payload {phone, status, priority, category}.
 *   4. Serialize và trả String.
 */
String buildSMSResultPacket(
    const String& originalPacketId,
    const String& phone,
    const String& status,
    int priority,
    const String& category
)
{
    DynamicJsonDocument doc(512);

    doc["type"] = PACKET_EVENT;

    doc["command"] = CMD_SMS_RESULT;

    doc["packet_id"] =
        originalPacketId;

    doc["source"] =
        "ESP32";

    doc["target"] =
        "AI_UI";

    doc["timestamp"] =
        millis();

    JsonObject payload =
        doc.createNestedObject(
            "payload"
        );

    payload["phone"] = phone;

    payload["status"] = status;

    payload["priority"] = priority;

    payload["category"] = category;

    String output;

    serializeJson(
        doc,
        output
    );

    return output;
}

// ============================================
// BUILD START / STOP MANUAL SMS PACKETS
// ============================================

/**
 * Chức năng: Xây dựng gói REQUEST START_MANUAL_SMS báo cho Python bắt đầu
 *            chế độ thu thập giọng nói thủ công.
 * Tham số: Không
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type REQUEST, command START_MANUAL_SMS.
 *   2. Serialize và trả String.
 */
String buildStartManualSMSPacket()
{
    DynamicJsonDocument doc(256);

    doc["type"]      = PACKET_REQUEST;
    doc["command"]   = CMD_START_MANUAL_SMS;
    doc["packet_id"] = generatePacketId("MSMS_START");
    doc["source"]    = "ESP32";
    doc["target"]    = "AI_UI";
    doc["timestamp"] = millis();

    String output;
    serializeJson(doc, output);
    return output;
}

/**
 * Chức năng: Xây dựng gói REQUEST STOP_MANUAL_SMS báo cho Python kết thúc
 *            chế độ thu thập giọng nói và gửi SMS.
 * Tham số: Không
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type REQUEST, command STOP_MANUAL_SMS.
 *   2. Serialize và trả String.
 */
String buildStopManualSMSPacket()
{
    DynamicJsonDocument doc(256);

    doc["type"]      = PACKET_REQUEST;
    doc["command"]   = CMD_STOP_MANUAL_SMS;
    doc["packet_id"] = generatePacketId("MSMS_STOP");
    doc["source"]    = "ESP32";
    doc["target"]    = "AI_UI";
    doc["timestamp"] = millis();

    String output;
    serializeJson(doc, output);
    return output;
}

// ============================================
// BUILD NEW SMS EVENT
// ============================================

/**
 * Chức năng: Xây dựng gói EVENT NEW_SMS thông báo cho Python về một tin
 *            nhắn SMS mới nhận được từ bên ngoài.
 * Tham số:
 *   - phone   : số điện thoại người gửi
 *   - message : nội dung tin nhắn (đã decode UTF-8)
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document 2048 bytes (đủ chứa tin nhắn dài).
 *   2. Thêm payload {phone, message}.
 *   3. Serialize và trả String.
 */
String buildNewSMSPacket(
    const String& phone,
    const String& message)
{
    DynamicJsonDocument doc(2048);

    doc["type"] = PACKET_EVENT;
    doc["command"] = CMD_NEW_SMS;
    doc["packet_id"] =
        generatePacketId("NEWSMS");
    doc["source"] =
        "ESP32";

    doc["target"] =
        "AI_UI";

    doc["timestamp"] =
        millis();

    JsonObject payload =
        doc.createNestedObject("payload");

    payload["phone"] = phone;
    payload["message"] = message;

    String output;

    serializeJson(doc, output);

    return output;
}

// ============================================
// BUILD SMS DELIVERY REPORT PACKET
// ============================================

/**
 * Chức năng: Xây dựng gói EVENT SMS_DELIVERY thông báo delivery report
 *            nhận được từ mạng (xác nhận SMS đã đến tay người nhận).
 * Tham số:
 *   - phone  : số điện thoại nhận SMS
 *   - status : trạng thái delivery ("DELIVERED" hoặc khác)
 *   - mr     : Message Reference number từ mạng GSM
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type EVENT, command SMS_DELIVERY.
 *   2. Thêm payload {phone, status, mr}.
 *   3. Serialize và trả String.
 */
String buildSMSDeliveryPacket(
    const String& phone,
    const String& status,
    int mr)
{
    DynamicJsonDocument doc(512);

    doc["type"]      = PACKET_EVENT;
    doc["command"]   = CMD_SMS_DELIVERY;
    doc["packet_id"] = generatePacketId("DELIV");
    doc["source"]    = "ESP32";
    doc["target"]    = "AI_UI";
    doc["timestamp"] = millis();

    JsonObject payload =
        doc.createNestedObject("payload");

    payload["phone"]  = phone;
    payload["status"] = status;
    payload["mr"]     = mr;

    String output;
    serializeJson(doc, output);
    return output;
}

// ============================================
// BUILD HEARTBEAT
// ============================================

/**
 * Chức năng: Xây dựng gói EVENT HEARTBEAT để ESP32 báo sống định kỳ
 *            cho Python theo dõi kết nối.
 * Tham số: Không
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type EVENT, command HEARTBEAT.
 *   2. Serialize và trả String.
 */
String buildHeartbeatPacket()
{
    DynamicJsonDocument doc(256);

    doc["type"] = PACKET_EVENT;
    doc["command"] = CMD_HEARTBEAT;

    doc["packet_id"] =
        generatePacketId("HB");

    doc["source"] =
        "ESP32";

    doc["target"] =
        "AI_UI";

    doc["timestamp"] =
        millis();

    String output;

    serializeJson(doc, output);

    return output;
}

// ============================================
// BUILD SYSTEM STATE PACKET
// ============================================

/**
 * Chức năng: Xây dựng gói STATE SYSTEM_STATE mang đầy đủ trạng thái
 *            phần cứng ESP32 gửi lên Python.
 * Tham số: Không
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type STATE, command SYSTEM_STATE.
 *   2. Đọc từ systemState: simReady, simInserted, networkReady,
 *      smsReady, signalStrength, uartConnected.
 *   3. Serialize và trả String.
 */
String buildSystemStatePacket()
{
    DynamicJsonDocument doc(1024);

    doc["type"] = PACKET_STATE;
    doc["command"] = CMD_SYSTEM_STATE;
    doc["packet_id"] =
        generatePacketId("SYS");
    doc["source"] =
        "ESP32";

    doc["target"] =
        "AI_UI";

    doc["timestamp"] =
        millis();

    JsonObject payload =
        doc.createNestedObject("payload");

    payload["sim_module"] =
        systemState.simReady;

    payload["sim_inserted"] =
        systemState.simInserted;

    payload["network_registered"] =
        systemState.networkReady;

    payload["sms_ready"] =
        systemState.smsReady;

    payload["signal"] =
        systemState.signalStrength;

    payload["uart_connected"] =
        systemState.uartConnected;

    String output;

    serializeJson(doc, output);

    return output;
}

/**
 * Chức năng: Xây dựng gói ACK phản hồi cho một packet đã nhận —
 *            báo cho bên gửi biết đã nhận thành công.
 * Tham số:
 *   - packetId : ID của gói tin cần ACK
 * Trả về: String JSON packet ACK
 * Luồng hoạt động:
 *   1. Tạo JSON document nhỏ với type ACK và packet_id gốc.
 *   2. Thêm status SUCCESS.
 *   3. Serialize và trả String.
 */
String buildAckPacket(
    const String& packetId)
{
    DynamicJsonDocument doc(256);

    doc["type"] = PACKET_ACK;

    doc["packet_id"] = packetId;

    doc["status"] = STATUS_SUCCESS;

    String output;

    serializeJson(doc, output);

    return output;
}

// ============================================
// BUILD STOP AUDIO PACKET
// ============================================

/**
 * Chức năng: Xây dựng gói REQUEST STOP_AUDIO khi người dùng nhấn phím A
 *            để dừng phát âm thanh TTS trên Python.
 * Tham số: Không
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type REQUEST, command STOP_AUDIO.
 *   2. Serialize và trả String.
 */
String buildStopAudioPacket()
{
    DynamicJsonDocument doc(256);

    doc["type"]      = PACKET_REQUEST;
    doc["command"]   = CMD_STOP_AUDIO;
    doc["packet_id"] = generatePacketId("STOP_AUDIO");
    doc["source"]    = "ESP32";
    doc["target"]    = "AI_UI";
    doc["timestamp"] = millis();

    String output;
    serializeJson(doc, output);
    return output;
}

// ============================================
// BUILD SOS PACKET
// ============================================

/**
 * Chức năng: Xây dựng gói REQUEST SOS khi người dùng nhấn nút SOS khẩn cấp
 *            để Python gửi cảnh báo đến tất cả liên hệ.
 * Tham số: Không
 * Trả về: String JSON packet
 * Luồng hoạt động:
 *   1. Tạo JSON document với type REQUEST, command SOS.
 *   2. Serialize và trả String.
 */
String buildSOSPacket()
{
    DynamicJsonDocument doc(256);

    doc["type"]      = PACKET_REQUEST;
    doc["command"]   = CMD_SOS;
    doc["packet_id"] = generatePacketId("SOS");
    doc["source"]    = "ESP32";
    doc["target"]    = "AI_UI";
    doc["timestamp"] = millis();

    String output;
    serializeJson(doc, output);
    return output;
}

/**
 * Chức năng: Kiểm tra xem đã đến lúc gửi heartbeat chưa dựa trên
 *            khoảng thời gian HEARTBEAT_INTERVAL.
 * Tham số: Không
 * Trả về: true nếu đã đến lúc gửi, false nếu chưa
 * Luồng hoạt động:
 *   1. So sánh millis() với lastHeartbeatTime.
 *   2. Nếu đã qua HEARTBEAT_INTERVAL: cập nhật lastHeartbeatTime và trả true.
 *   3. Ngược lại trả false.
 */
bool shouldSendHeartbeat()
{
    unsigned long currentMillis = millis();

    if (currentMillis - systemState.lastHeartbeatTime
        >= HEARTBEAT_INTERVAL)
    {
        systemState.lastHeartbeatTime = currentMillis;

        return true;
    }

    return false;
}
