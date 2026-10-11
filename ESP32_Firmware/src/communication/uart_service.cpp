#include <Arduino.h>
#include <ArduinoJson.h>

#include "config.h"
#include "packet.h"
#include "debug.h"

// ============================================
// UART INSTANCE
// ============================================

HardwareSerial SerialAT(2);

// ============================================
// ACK MANAGER
// ============================================

extern void addPendingPacket(
    const String& packetId,
    const String& packetData);

// ============================================
// INIT UART
// ============================================

/**
 * Chức năng: Khởi tạo cổng Serial giao tiếp với Python — tăng buffer RX
 *            lên 1024 bytes để tránh overflow khi sync danh bạ.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Tăng RX buffer lên 1024 bytes.
 *   2. Khởi tạo Serial với UART_BAUD_RATE.
 */
void initUART()
{
    // Tăng buffer từ 256 lên 1024 bytes để tránh overflow khi sync contacts
    Serial.setRxBufferSize(1024);
    Serial.begin(UART_BAUD_RATE);

    Serial.println(
        "[UART] Initialized");
}

// ============================================
// SEND RAW PACKET
// ============================================

/**
 * Chức năng: Gửi chuỗi JSON thô ra Serial với ký tự newline — không theo dõi ACK.
 *            Dùng Serial.print(str+"\n") để đảm bảo ghi atomic trên cả hai core.
 * Tham số:
 *   - packet : chuỗi JSON gói tin cần gửi
 * Trả về: void
 * Luồng hoạt động:
 *   1. Gọi Serial.print(packet + "\n") — atomic, tránh interleave đa core.
 *   2. Log debug gói đã gửi.
 */
void sendRawPacket(
    const String& packet)
{
    // Serial.print(str+"\n") là 1 lần uartWrite duy nhất → atomic,
    // tránh interleave khi nhiều task gọi đồng thời từ 2 core
    Serial.print(packet + "\n");

    DEBUG_PRINTLN(
        "[UART] Packet TX");

    DEBUG_PRINTLN(packet);
}

// ============================================
// SEND TRACKED PACKET
// ============================================

/**
 * Chức năng: Gửi gói tin qua Serial và đăng ký vào AckManager để theo dõi
 *            ACK và tự động gửi lại nếu timeout.
 * Tham số:
 *   - packet   : chuỗi JSON gói tin cần gửi
 *   - packetId : ID gói tin để AckManager theo dõi
 * Trả về: void
 * Luồng hoạt động:
 *   1. Gửi gói qua Serial.print().
 *   2. Nếu packetId không rỗng: gọi addPendingPacket() để AckManager theo dõi.
 */
void sendTrackedPacket(
    const String& packet,
    const String& packetId)
{
    Serial.print(packet + "\n");

    DEBUG_PRINT(
        "[UART] Tracked TX : ");

    DEBUG_PRINTLN(packetId);

    DEBUG_PRINTLN(packet);

    if (packetId.length() > 0)
    {
        addPendingPacket(
            packetId,
            packet);
    }
}

// ============================================
// SEND JSON PACKET
// ============================================

/**
 * Chức năng: Xây dựng và gửi gói JSON từ các tham số rời — tiện dụng
 *            khi không dùng packet_builder.
 * Tham số:
 *   - type      : loại gói (COMMAND, EVENT, STATE, ACK...)
 *   - command   : lệnh trong gói
 *   - payload   : JsonObject chứa dữ liệu payload
 *   - status    : trường status tùy chọn
 *   - errorCode : mã lỗi tùy chọn
 * Trả về: void
 * Luồng hoạt động:
 *   1. Tạo JSON document 1024 bytes.
 *   2. Thêm type, command, status (nếu có), errorCode (nếu có).
 *   3. Copy toàn bộ cặp key-value từ payload vào doc.
 *   4. Serialize và gửi qua Serial.println().
 */
void sendPacket(
    const String& type,
    const String& command,
    JsonObject payload,
    const String& status = "",
    const String& errorCode = "")
{
    DynamicJsonDocument doc(1024);

    doc["type"] = type;

    doc["command"] = command;

    if (status.length() > 0)
    {
        doc["status"] = status;
    }

    if (errorCode.length() > 0)
    {
        doc["error_code"] =
            errorCode;
    }

    JsonObject payloadObj =
        doc.createNestedObject(
            "payload");

    for (JsonPair kv : payload)
    {
        payloadObj[kv.key()] =
            kv.value();
    }

    String output;

    serializeJson(
        doc,
        output);

    Serial.println(output);

    DEBUG_PRINTLN(
        "[UART] JSON TX");

    DEBUG_PRINTLN(output);
}

// ============================================
// READ PACKET
// ============================================

/**
 * Chức năng: Đọc từng byte từ Serial, tích lũy vào buffer tĩnh cho đến khi
 *            gặp newline thì trả về gói tin hoàn chỉnh.
 * Tham số:
 *   - output : tham chiếu String nhận gói tin khi hoàn chỉnh
 * Trả về: true nếu có gói hoàn chỉnh, false nếu chưa có
 * Luồng hoạt động:
 *   1. Đọc tất cả byte có sẵn trong Serial buffer.
 *   2. Bỏ qua ký tự CR ('\r').
 *   3. Khi gặp LF ('\n'): copy buffer vào output, xóa buffer, trả true.
 *   4. Thêm ký tự vào buffer; nếu vượt MAX_PACKET_SIZE thì xóa buffer (drop).
 *   5. Trả false nếu chưa hoàn chỉnh.
 */
bool readPacket(
    String& output)
{
    static String buffer = "";

    while (Serial.available())
    {
        char c = Serial.read();

        // Ignore CR
        if (c == '\r')
        {
            continue;
        }

        // Packet End
        if (c == '\n')
        {
            if (buffer.length() == 0)
            {
                continue;
            }

            output = buffer;

            buffer = "";

            DEBUG_PRINTLN(
                "[UART] Packet RX");

            DEBUG_PRINTLN(output);

            return true;
        }

        buffer += c;

        if (buffer.length() >
            MAX_PACKET_SIZE)
        {
            Serial.println(
                "[UART] ERR: Packet too large, dropped");

            buffer = "";
        }
    }

    return false;
}
