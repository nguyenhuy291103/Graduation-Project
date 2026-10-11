#include <Arduino.h>

// ============================================
// EXTERNAL
// ============================================

extern bool shouldSendHeartbeat();

extern String buildHeartbeatPacket();

extern void sendRawPacket(
    const String& packet);

// ============================================
// HEARTBEAT TASK
// ============================================

/**
 * Chức năng: Task FreeRTOS gửi heartbeat định kỳ sang Python để duy trì
 *            trạng thái kết nối và theo dõi sức khỏe hệ thống.
 * Tham số:
 *   - parameter : con trỏ tham số FreeRTOS (không dùng)
 * Trả về: void (task chạy vĩnh viễn)
 * Luồng hoạt động:
 *   1. Kiểm tra điều kiện gửi heartbeat qua shouldSendHeartbeat().
 *   2. Nếu đến giờ, xây dựng gói heartbeat và gửi qua UART.
 *   3. Delay 1000ms trước khi lặp lại.
 */
void heartbeatTask(void* parameter)
{
    while (true)
    {
        if (shouldSendHeartbeat())
        {
            String packet =
                buildHeartbeatPacket();

            sendRawPacket(packet);
        }

        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
}
