#include <Arduino.h>
#include <LiquidCrystal_I2C.h>

#include "config.h"
#include "system_state.h"

extern SemaphoreHandle_t lcdMutex;

// ============================================
// LCD
// ============================================

LiquidCrystal_I2C lcd(
    LCD_I2C_ADDRESS,
    LCD_COLUMNS,
    LCD_ROWS);

// ============================================
// INIT LCD
// ============================================

/**
 * Chức năng: Khởi tạo màn hình LCD I2C và hiển thị thông báo khởi động
 *            "AI SYSTEM / STARTING...".
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Gọi lcd.init() và bật đèn nền.
 *   2. Xóa màn hình và in "AI SYSTEM" dòng 0, "STARTING..." dòng 1.
 */
void initLCD()
{
    lcd.init();

    lcd.backlight();

    lcd.clear();

    lcd.setCursor(0, 0);
    lcd.print("AI SYSTEM");

    lcd.setCursor(0, 1);
    lcd.print("STARTING...");
}

// ============================================
// UPDATE LCD
// ============================================

/**
 * Chức năng: Cập nhật nội dung LCD từ systemState.lcdLine1/2 — chỉ vẽ lại
 *            khi có thay đổi để tránh nhấp nháy.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Lấy lcdMutex để đọc lcdLine1/2 an toàn từ đa core.
 *   2. So sánh với lastLine1/lastLine2; trả về ngay nếu không đổi.
 *   3. Cập nhật lastLine1/lastLine2, xóa màn hình và in hai dòng mới.
 */
void updateLCD()
{
    static String lastLine1 = "";
    static String lastLine2 = "";

    // Atomic snapshot: prevents torn read when simTask (Core 0) writes
    // lcdLine1+2 while inputTask (Core 1) reads them simultaneously
    if (lcdMutex != NULL) xSemaphoreTake(lcdMutex, portMAX_DELAY);
    String line1 = systemState.lcdLine1;
    String line2 = systemState.lcdLine2;
    if (lcdMutex != NULL) xSemaphoreGive(lcdMutex);

    if (lastLine1 == line1 && lastLine2 == line2)
    {
        return;
    }

    lastLine1 = line1;
    lastLine2 = line2;

    lcd.clear();

    lcd.setCursor(0, 0);
    lcd.print(line1);

    lcd.setCursor(0, 1);
    lcd.print(line2);
}
