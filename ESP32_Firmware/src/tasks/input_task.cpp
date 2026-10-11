#include <Arduino.h>

// ============================================
// EXTERNAL
// ============================================

extern void handleKeypad();

extern void handleButtons();

extern void updateLCD();

extern void updateLCDPopup();

// ============================================
// INPUT TASK
// ============================================

/**
 * Chức năng: Task FreeRTOS xử lý đầu vào người dùng (keypad, nút nhấn)
 *            và cập nhật hiển thị LCD theo chu kỳ 50ms.
 * Tham số:
 *   - parameter : con trỏ tham số FreeRTOS (không dùng)
 * Trả về: void (task chạy vĩnh viễn)
 * Luồng hoạt động:
 *   1. Xử lý keypad ma trận 4x4.
 *   2. Xử lý các nút nhấn rời (A, B, SOS).
 *   3. Cập nhật popup LCD nếu đang hiển thị.
 *   4. Cập nhật màn hình LCD chính.
 *   5. Delay 50ms trước khi lặp lại.
 */
void inputTask(void* parameter)
{
    while (true)
    {
        handleKeypad();

        handleButtons();

        updateLCDPopup();

        updateLCD();

        vTaskDelay(50 / portTICK_PERIOD_MS);
    }
}
