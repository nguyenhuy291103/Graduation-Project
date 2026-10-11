#ifndef ACK_MANAGER_H
#define ACK_MANAGER_H

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#define MAX_PENDING_PACKETS 20

struct PendingPacket
{
    String packetId;

    String packetData;      // JSON đầy đủ để retry

    unsigned long timestamp;

    bool acknowledged;

    int retryCount;
};

/**
 * Chức năng: Khởi tạo AckManager — xóa toàn bộ bảng pending packets.
 * Tham số: Không
 * Trả về: void
 */
void initAckManager();

/**
 * Chức năng: Thêm gói tin vào bảng pending để theo dõi ACK và retry.
 * Tham số:
 *   - packetId   : ID gói tin cần theo dõi
 *   - packetData : chuỗi JSON gốc để gửi lại khi timeout
 * Trả về: void
 */
void addPendingPacket(
    const String& packetId,
    const String& packetData = "");

/**
 * Chức năng: Đánh dấu gói tin đã được ACK (acknowledged = true).
 * Tham số:
 *   - packetId : ID gói tin vừa nhận được ACK
 * Trả về: void
 */
void acknowledgePacket(
    const String& packetId);

/**
 * Chức năng: Kiểm tra các gói tin quá hạn ACK và gửi lại nếu chưa vượt
 *            MAX_RETRY_COUNT; xóa khỏi bảng nếu đã retry đủ lần.
 * Tham số: Không
 * Trả về: void
 */
void checkPacketTimeouts();

#endif
