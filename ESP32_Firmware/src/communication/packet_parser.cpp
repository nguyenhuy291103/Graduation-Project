#include <Arduino.h>
#include <ArduinoJson.h>

#include "packet.h"

// ============================================
// PARSE PACKET
// ============================================

/**
 * Chức năng: Parse chuỗi JSON thô từ UART thành struct Packet có cấu trúc.
 * Tham số:
 *   - jsonString : chuỗi JSON thô nhận từ Serial
 *   - packet     : tham chiếu struct Packet sẽ được điền dữ liệu
 * Trả về: true nếu parse thành công, false nếu JSON lỗi hoặc thiếu trường bắt buộc
 * Luồng hoạt động:
 *   1. Deserialize JSON vào DynamicJsonDocument 2048 bytes.
 *   2. Kiểm tra lỗi parse; in log và trả false nếu có.
 *   3. Đọc các trường bắt buộc type và command; trả false nếu thiếu.
 *   4. Đọc các trường tùy chọn: status, errorCode, packetId, source, target, timestamp.
 *   5. Serialize payload thành chuỗi JSON hoặc đặt "{}" nếu không có.
 */
bool parsePacket(const String& jsonString, Packet& packet)
{
    DynamicJsonDocument doc(2048);

    DeserializationError error = deserializeJson(doc, jsonString);

    if (error)
    {
        Serial.println("[PARSER] JSON Parse Failed");

        return false;
    }

    // ========================================
    // REQUIRED
    // ========================================

    packet.type    = doc["type"]    | "";
    packet.command = doc["command"] | "";

    if (packet.type.isEmpty() || packet.command.isEmpty())
    {
        Serial.println("[PARSER] Missing type or command");
        return false;
    }

    // ========================================
    // OPTIONAL
    // ========================================

    packet.status = doc["status"] | "";
    packet.errorCode = doc["error_code"] | "";

    packet.packetId = doc["packet_id"] | "";

    packet.source = doc["source"] | "";
    packet.target = doc["target"] | "";

    packet.timestamp = doc["timestamp"] | 0;

    // ========================================
    // PAYLOAD
    // ========================================

    if (doc.containsKey("payload"))
    {
        String payloadString;

        serializeJson(doc["payload"], payloadString);

        packet.payload = payloadString;
    }
    else
    {
        packet.payload = "{}";
    }

    return true;
}

// ============================================
// GET PAYLOAD DOC
// ============================================

/**
 * Chức năng: Parse chuỗi JSON payload thành DynamicJsonDocument để truy cập
 *            các trường riêng lẻ trong payload của gói tin.
 * Tham số:
 *   - payloadString : chuỗi JSON của payload (từ Packet.payload)
 *   - payloadDoc    : tham chiếu DynamicJsonDocument sẽ được điền
 * Trả về: true nếu parse thành công, false nếu JSON lỗi
 * Luồng hoạt động:
 *   1. Deserialize payloadString vào payloadDoc.
 *   2. In log lỗi và trả false nếu có lỗi.
 *   3. Trả true nếu thành công.
 */
bool parsePayload(
    const String& payloadString,
    DynamicJsonDocument& payloadDoc)
{
    DeserializationError error =
        deserializeJson(payloadDoc, payloadString);

    if (error)
    {
        Serial.print(
            "[PARSER] JSON Parse Failed : ");

        Serial.println(
            error.c_str());

        return false;
    }

    return true;
}
