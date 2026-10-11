#include <Arduino.h>

extern void
checkPacketTimeouts();

/**
 * Chức năng: Task FreeRTOS kiểm tra định kỳ các gói tin đang chờ ACK
 *            và gửi lại nếu quá thời gian timeout.
 * Tham số:
 *   - parameter : con trỏ tham số FreeRTOS (không dùng)
 * Trả về: void (task chạy vĩnh viễn)
 * Luồng hoạt động:
 *   1. Gọi checkPacketTimeouts() để kiểm tra và gửi lại gói hết hạn.
 *   2. Delay 1000ms trước khi lặp lại.
 */
void ackTask(
    void* parameter
)
{
    while(true)
    {
        checkPacketTimeouts();

        vTaskDelay(
            1000 /
            portTICK_PERIOD_MS
        );
    }
}
