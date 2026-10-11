#include <Arduino.h>

// ============================================
// EXTERNAL
// ============================================

extern void handleSIMIncoming();
extern void checkSIMStatus();
extern String buildSystemStatePacket();
extern void sendRawPacket(const String& packet);

// ============================================
// SIM TASK
// ============================================

/**
 * Chức năng: Task FreeRTOS quản lý module SIM — kiểm tra trạng thái ban đầu,
 *            xử lý SMS đến và làm mới định kỳ trạng thái mạng mỗi 60 giây.
 * Tham số:
 *   - parameter : con trỏ tham số FreeRTOS (không dùng)
 * Trả về: void (task chạy vĩnh viễn)
 * Luồng hoạt động:
 *   1. Kiểm tra trạng thái SIM lần đầu sau khi initSIM() đã chạy xong.
 *   2. Gửi gói SYSTEM_STATE ngay lập tức để Python nhận trạng thái đúng.
 *   3. Vòng lặp: xử lý SMS/cuộc gọi đến qua handleSIMIncoming().
 *   4. Mỗi 60 giây: làm mới trạng thái SIM và mạng.
 *   5. Delay 100ms giữa mỗi vòng để nhường CPU cho các task khác.
 */
void simTask(void* parameter)
{
    // Run an initial status check so SIM flags are set even if Python
    // never sends CMD_CHECK_SYSTEM. initSIM() finishes before tasks
    // start, so the module is ready by the time we reach this line.
    checkSIMStatus();

    // Push state to Python immediately after boot check.
    // If Python isn't connected yet, this is a no-op on the UART TX side.
    // If it IS connected (e.g., hot-reconnect), Python gets correct state
    // without having to request it.
    sendRawPacket(buildSystemStatePacket());

    unsigned long lastCheck = millis();

    while (true)
    {
        handleSIMIncoming();

        // Periodic status refresh — keeps flags current if network
        // drops or SIM is re-inserted after initial boot check.
        if (millis() - lastCheck >= 60000)
        {
            lastCheck = millis();
            checkSIMStatus();
        }

        vTaskDelay(100 / portTICK_PERIOD_MS);
    }
}
