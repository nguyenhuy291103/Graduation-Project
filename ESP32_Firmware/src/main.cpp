// ============================================
// main.cpp
// ============================================

#include <Arduino.h>

#include "config.h"

#include "sms_task.h"

// ============================================
// EXTERNAL
// ============================================

// CORE

extern void initializeSystem();

// ACK MANAGER

extern void initAckManager();

// TASKS

extern void uartTask(
    void* parameter);

extern void simTask(
    void* parameter);

extern void inputTask(
    void* parameter);

extern void heartbeatTask(
    void* parameter);

extern void ackTask(
    void* parameter
);

// ============================================
// SETUP
// ============================================

/**
 * Chức năng: Hàm khởi tạo Arduino — chạy một lần khi ESP32 reset.
 *            Khởi tạo tất cả phần cứng và tạo toàn bộ FreeRTOS task.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Gọi initializeSystem(): UART, LCD, Keypad, Nút, SIM, ContactManager,
 *      mutex, hàng đợi SMS.
 *   2. Khởi tạo AckManager (mutex + bộ đệm pending).
 *   3. Tạo uartTask (core 1, priority 3) — đọc lệnh từ Python.
 *   4. Tạo smsTask (core 0, priority 1) — gửi SMS từ hàng đợi.
 *   5. Tạo ackTask (core 1, priority 2) — kiểm tra timeout gói tin.
 *   6. Tạo simTask (core 0, priority 2) — quản lý module SIM.
 *   7. Tạo inputTask (core 1, priority 2) — keypad và nút nhấn.
 *   8. Tạo heartbeatTask (core 1, priority 2) — gửi heartbeat định kỳ.
 */
void setup()
{
    // ========================================
    // SYSTEM INIT
    // ========================================

    initializeSystem();

    // ========================================
    // ACK MANAGER
    // ========================================

    initAckManager();

    Serial.println(
        "[ACK] Manager Initialized");

    // ========================================
    // UART TASK
    // ========================================

    // uartTask: priority cao nhất — đọc UART kịp thời
    xTaskCreatePinnedToCore(
        uartTask,
        "UART Task",
        4096,
        NULL,
        3,
        NULL,
        1);

    // smsTask: priority thấp, chạy core 0 — không tranh CPU với uartTask
    xTaskCreatePinnedToCore(
        smsTask,
        "SMS Task",
        4096,
        NULL,
        1,
        NULL,
        0);

    xTaskCreatePinnedToCore(
        ackTask,
        "ACK Task",
        4096,
        NULL,
        2,
        NULL,
        1);

    // ========================================
    // SIM TASK — core 0, không tranh với UART
    // ========================================

    xTaskCreatePinnedToCore(
        simTask,
        "SIM Task",
        4096,
        NULL,
        2,
        NULL,
        0);

    // ========================================
    // INPUT TASK
    // ========================================

    xTaskCreatePinnedToCore(
        inputTask,
        "Input Task",
        4096,
        NULL,
        2,
        NULL,
        1);

    // ========================================
    // HEARTBEAT TASK
    // ========================================

    xTaskCreatePinnedToCore(
        heartbeatTask,
        "Heartbeat Task",
        4096,
        NULL,
        2,
        NULL,
        1);

    Serial.println(
        "[SYSTEM] Tasks Started");
}

// ============================================
// LOOP
// ============================================

/**
 * Chức năng: Vòng lặp chính Arduino — không làm gì vì toàn bộ logic
 *            đã được phân chia vào các FreeRTOS task riêng biệt.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Delay 1 giây để nhường CPU cho scheduler.
 */
void loop()
{
    delay(1000);
}
