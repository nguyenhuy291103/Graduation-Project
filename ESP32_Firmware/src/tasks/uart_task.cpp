#include <Arduino.h>
#include <ArduinoJson.h>

#include "packet.h"
#include "system_state.h"
#include "debug.h"
#include "contact_manager.h"

// ============================================
// EXTERNAL
// ============================================

extern bool readPacket(String& output);

extern bool parsePacket(
    const String& jsonString,
    Packet& packet);

extern bool parsePayload(
    const String& payloadString,
    DynamicJsonDocument& payloadDoc);

extern void sendSMS(
    const String& packetId,
    const String& phone,
    const String& message,
    int priority,
    const String& category
);

extern void showLCDMessage(
    const String& line1,
    const String& line2);

extern void updateLCD();

extern String buildSystemStatePacket();

extern String buildSMSResultPacket(
    const String& originalPacketId,
    const String& phone,
    const String& status,
    int priority,
    const String& category
);

extern void sendRawPacket(
    const String& packet);

extern String buildAckPacket(
    const String& packetId);

extern void acknowledgePacket(
    const String& packetId);

extern void checkSIMStatus();

// ============================================
// UART TASK
// ============================================

/**
 * Chức năng: Task FreeRTOS đọc và xử lý các gói lệnh từ Python qua UART —
 *            điều phối toàn bộ giao tiếp UART giữa ESP32 và AI_UI.
 * Tham số:
 *   - parameter : con trỏ tham số FreeRTOS (không dùng)
 * Trả về: void (task chạy vĩnh viễn)
 * Luồng hoạt động:
 *   1. Đọc gói UART thô; nếu không có thì delay 10ms và tiếp tục.
 *   2. Parse JSON thành struct Packet; log lỗi nếu thất bại.
 *   3. Nếu là ACK: xóa gói khỏi hàng đợi pending và tiếp tục.
 *   4. Gửi ACK phản hồi cho mọi gói có packetId.
 *   5. Xử lý theo lệnh: CHECK_SYSTEM, GET_SYSTEM_STATE, SEND_SMS,
 *      SYNC_CONTACT, DELETE_CONTACT, SYNC_CONTACTS_CLEAR, ADD_CONTACT response.
 *   6. Log lệnh không nhận dạng được.
 */
void uartTask(void* parameter)
{
    String rawPacket;

    Packet packet;

    while (true)
    {
        if (readPacket(rawPacket))
        {
            DEBUG_PRINTLN(
                "[UART TASK] Packet RX");

            if (parsePacket(rawPacket, packet))
            {
                // ====================================
                // ACK PACKET
                // ====================================

                if (packet.type == PACKET_ACK)
                {
                    acknowledgePacket(
                        packet.packetId);

                    DEBUG_PRINT(
                        "[UART TASK] ACK RX : ");

                    DEBUG_PRINTLN(
                        packet.packetId);

                    vTaskDelay(
                        10 / portTICK_PERIOD_MS);

                    continue;
                }

                // ====================================
                // SEND ACK
                // ====================================

                if (packet.packetId.length() > 0)
                {
                    String ackPacket =
                        buildAckPacket(
                            packet.packetId);

                    sendRawPacket(
                        ackPacket);

                    DEBUG_PRINT(
                        "[UART TASK] ACK TX : ");

                    DEBUG_PRINTLN(
                        packet.packetId);
                }


                if(packet.command ==
                    CMD_CHECK_SYSTEM)
                {
                    DEBUG_PRINTLN(
                        "[UART TASK] CHECK SYSTEM");

                    checkSIMStatus();

                    String statePacket =
                        buildSystemStatePacket();

                    sendRawPacket(
                        statePacket);

                    continue;
                }

                // ====================================
                // GET SYSTEM STATE
                // ====================================

                if (packet.command ==
                    CMD_GET_SYSTEM_STATE)
                {
                    String statePacket =
                        buildSystemStatePacket();

                    sendRawPacket(
                        statePacket);

                    DEBUG_PRINTLN(
                        "[UART TASK] SYSTEM STATE TX");

                    continue;
                }

                // ====================================
                // SEND SMS
                // ====================================

                if (packet.command ==
                        CMD_SEND_SMS ||
                    packet.command ==
                        CMD_SEND_MANUAL_SMS)
                {
                    DynamicJsonDocument payload(
                        2048);

                    if (parsePayload(
                        packet.payload,
                        payload))
                    {
                        String phone =
                            payload["phone"] | "";

                        String message =
                            payload["message"] | "";

                        int priority =
                            payload["priority"] | 3;

                        String category =
                            payload["category"] | "";

                        DEBUG_PRINT(
                            "[UART TASK] SEND SMS : ");

                        DEBUG_PRINT(
                            "Priority: "
                        );

                        DEBUG_PRINTLN(
                            priority
                        );

                        DEBUG_PRINT(
                            "Category: "
                        );

                        DEBUG_PRINTLN(
                            category
                        );

                        DEBUG_PRINTLN(
                            phone);

                        SMSJob job;

                        memset(&job, 0, sizeof(job));

                        strncpy(
                            job.packetId,
                            packet.packetId.c_str(),
                            sizeof(job.packetId) - 1
                        );

                        strncpy(
                            job.phone,
                            phone.c_str(),
                            sizeof(job.phone) - 1
                        );

                        strncpy(
                            job.message,
                            message.c_str(),
                            sizeof(job.message) - 1
                        );

                        job.priority = priority;

                        strncpy(
                            job.category,
                            category.c_str(),
                            sizeof(job.category) - 1
                        );

                        if (smsQueue != nullptr &&
                            xQueueSend(
                                smsQueue,
                                &job,
                                pdMS_TO_TICKS(100)
                            ) == pdTRUE
                        )
                        {
                            DEBUG_PRINTLN(
                                "[UART] SMS QUEUED"
                            );
                        }
                        else
                        {
                            DEBUG_PRINTLN(
                                "[UART] SMS QUEUE FULL OR NULL"
                            );

                            String failPacket =
                                buildSMSResultPacket(
                                    packet.packetId,
                                    phone,
                                    "FAILED",
                                    priority,
                                    category
                                );

                            sendRawPacket(failPacket);
                        }
                    }
                    else
                    {
                        DEBUG_PRINTLN(
                            "[UART TASK] SMS PAYLOAD ERROR");
                    }

                    continue;
                }

                // ====================================
                // SYNC CONTACT (add / update)
                // ====================================

                if (packet.command ==
                    CMD_SYNC_CONTACT)
                {
                    DynamicJsonDocument payload(512);

                    if (parsePayload(
                        packet.payload,
                        payload))
                    {
                        String id       = payload["id"]       | "";
                        String phone    = payload["phone"]    | "";
                        String name     = payload["name"]     | "";
                        String relation = payload["relation"] | "";

                        syncContact(id, phone, name, relation);

                        DEBUG_PRINT("[CONTACT] SYNC: ");
                        DEBUG_PRINTLN(id);
                    }

                    continue;
                }

                // ====================================
                // DELETE CONTACT LOCAL
                // ====================================

                if (packet.command ==
                    CMD_DELETE_CONTACT)
                {
                    DynamicJsonDocument payload(256);

                    if (parsePayload(
                        packet.payload,
                        payload))
                    {
                        String id = payload["id"] | "";
                        deleteContactLocal(id);

                        DEBUG_PRINT("[CONTACT] DELETE: ");
                        DEBUG_PRINTLN(id);
                    }

                    continue;
                }

                // ====================================
                // SYNC CONTACTS CLEAR
                // ====================================

                if (packet.command ==
                    CMD_SYNC_CONTACTS_CLEAR)
                {
                    clearAllContacts();

                    DEBUG_PRINTLN("[CONTACT] CLEAR ALL");

                    continue;
                }

                // ====================================
                // ADD CONTACT RESPONSE
                // ====================================

                if (packet.type ==
                        PACKET_RESPONSE &&
                    packet.command ==
                        CMD_ADD_CONTACT)
                {
                    // SUCCESS

                    if (packet.status ==
                        STATUS_SUCCESS)
                    {
                        showLCDMessage(
                            "CONTACT SAVED",
                            "SUCCESS");

                        updateLCD();
                    }

                    // ERROR

                    else if (packet.status ==
                             STATUS_ERROR ||
                             packet.status ==
                             "FAILED")
                    {
                        if (packet.errorCode ==
                            ERROR_ID_EXISTS)
                        {
                            showLCDMessage(
                                "ID EXISTS",
                                "TRY AGAIN");

                            updateLCD();
                        }
                        else if (packet.errorCode ==
                            ERROR_PHONE_EXISTS)
                        {
                            showLCDMessage(
                                "PHONE EXISTS",
                                "TRY AGAIN");

                            updateLCD();
                        }
                        else if (packet.errorCode ==
                                 ERROR_INVALID_PHONE)
                        {
                            showLCDMessage(
                                "INVALID PHONE",
                                "TRY AGAIN");

                            updateLCD();
                        }
                        else
                        {
                            showLCDMessage(
                                "SAVE FAILED",
                                "TRY AGAIN");

                            updateLCD();
                        }
                    }

                    continue;
                }

                // ====================================
                // UNKNOWN COMMAND
                // ====================================

                DEBUG_PRINT(
                    "[UART TASK] Unknown Command : ");

                DEBUG_PRINTLN(
                    packet.command);
            }
            else
            {
                DEBUG_PRINTLN(
                    "[UART TASK] Parse Failed");
            }
        }

        vTaskDelay(
            10 / portTICK_PERIOD_MS);
    }
}
