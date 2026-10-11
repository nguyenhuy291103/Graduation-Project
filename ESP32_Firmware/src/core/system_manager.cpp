#include <Arduino.h>

#include "config.h"
#include "debug.h"
#include "system_state.h"

// ============================================
// EXTERNAL FUNCTIONS
// ============================================

extern void initUART();
extern void initLCD();
extern void initKeypad();
extern void initButtons();
extern void initSIM();
extern void initContactManager();

// ============================================
// GLOBAL STATE
// ============================================

SystemState systemState;

QueueHandle_t smsQueue = nullptr;

bool sendingSMS = false;

SemaphoreHandle_t simMutex = NULL;
SemaphoreHandle_t lcdMutex = NULL;

// ============================================
// SYSTEM INIT
// ============================================

/**
 * Chức năng: Khởi tạo toàn bộ phần cứng và tài nguyên hệ thống theo thứ tự
 *            phụ thuộc: UART → LCD → Keypad → Nút → SIM → ContactManager →
 *            mutex → hàng đợi SMS.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Khởi tạo tuần tự: UART, LCD, Keypad, Buttons, SIM, ContactManager.
 *   2. Tạo simMutex để bảo vệ truy cập module SIM từ nhiều task.
 *   3. Tạo lcdMutex để bảo vệ truy cập LCD.
 *   4. Tạo smsQueue (10 phần tử SMSJob) cho giao tiếp giữa uartTask và smsTask.
 */
void initializeSystem()
{
    initUART();
    initLCD();
    initKeypad();
    initButtons();
    initSIM();
    initContactManager();

    simMutex = xSemaphoreCreateMutex();
    if (simMutex == NULL)
        DEBUG_PRINTLN("[SIM MUTEX] CREATE FAILED");
    else
        DEBUG_PRINTLN("[SIM MUTEX] READY");

    lcdMutex = xSemaphoreCreateMutex();

    smsQueue = xQueueCreate(10, sizeof(SMSJob));
    if (smsQueue == nullptr)
        DEBUG_PRINTLN("[SYSTEM] SMS Queue Failed");
    else
        DEBUG_PRINTLN("[SYSTEM] SMS Queue Ready");

    Serial.println("[SYSTEM] Initialized");
}

// ============================================
// LCD POPUP SHOW
// ============================================

/**
 * Chức năng: Hiển thị thông báo popup trên LCD (2 dòng) trong khoảng thời gian
 *            LCD_MESSAGE_TIMEOUT mili giây rồi tự tắt.
 * Tham số:
 *   - line1 : văn bản dòng trên LCD
 *   - line2 : văn bản dòng dưới LCD
 * Trả về: void
 * Luồng hoạt động:
 *   1. Lấy lcdMutex (nếu có).
 *   2. Đặt lcdPopupActive=true, ghi timestamp bắt đầu và nội dung 2 dòng.
 *   3. Trả mutex.
 */
void showLCDMessage(
    const String& line1,
    const String& line2)
{
    if (lcdMutex != NULL) xSemaphoreTake(lcdMutex, portMAX_DELAY);
    systemState.lcdPopupActive = true;
    systemState.lcdPopupStart  = millis();
    systemState.lcdLine1       = line1;
    systemState.lcdLine2       = line2;
    if (lcdMutex != NULL) xSemaphoreGive(lcdMutex);
}

// ============================================
// LCD POPUP TIMEOUT
// ============================================

/**
 * Chức năng: Kiểm tra và tắt popup LCD khi đã hết thời gian hiển thị,
 *            phục hồi nội dung LCD theo trạng thái nhập liệu hiện tại.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Thoát sớm nếu không có popup đang hiển thị.
 *   2. Thoát nếu chưa hết LCD_MESSAGE_TIMEOUT.
 *   3. Lấy lcdMutex; đặt lcdPopupActive=false.
 *   4. Khôi phục nội dung LCD theo inputState:
 *      - INPUT_CONTACT_ID   → hiện "ADD ID: <currentContactId>"
 *      - INPUT_CONTACT_PHONE → hiện "ADD PHONE: <currentContactPhone>"
 *      - Khác               → hiện SYSTEM_NAME và dòng trống.
 *   5. Trả mutex.
 */
void updateLCDPopup()
{
    // Early exit — bool read is atomic on Xtensa, no mutex needed
    if (!systemState.lcdPopupActive)
        return;

    if (millis() - systemState.lcdPopupStart < LCD_MESSAGE_TIMEOUT)
        return;

    if (lcdMutex != NULL) xSemaphoreTake(lcdMutex, portMAX_DELAY);

    systemState.lcdPopupActive = false;

    if (systemState.inputState == INPUT_CONTACT_ID)
    {
        systemState.lcdLine1 = "ADD ID:";
        systemState.lcdLine2 = systemState.currentContactId;
    }
    else if (systemState.inputState == INPUT_CONTACT_PHONE)
    {
        systemState.lcdLine1 = "ADD PHONE:";
        systemState.lcdLine2 = systemState.currentContactPhone;
    }
    else
    {
        systemState.lcdLine1 = SYSTEM_NAME;
        systemState.lcdLine2 = "";
    }

    if (lcdMutex != NULL) xSemaphoreGive(lcdMutex);
}

// ============================================
// INPUT RESET
// ============================================

/**
 * Chức năng: Xóa dữ liệu nhập liệu liên hệ đang dở và đặt lại trạng thái
 *            nhập liệu về INPUT_IDLE.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Xóa currentContactId và currentContactPhone.
 *   2. Đặt inputState = INPUT_IDLE.
 */
void resetContactInput()
{
    systemState.currentContactId    = "";
    systemState.currentContactPhone = "";
    systemState.inputState          = INPUT_IDLE;
}
