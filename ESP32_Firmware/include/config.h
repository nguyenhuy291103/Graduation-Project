#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

#define UART_BAUD_RATE         115200


#define LCD_COLUMNS            16
#define LCD_ROWS               2
#define LCD_I2C_ADDRESS        0x27

#define KEYPAD_ROWS            4
#define KEYPAD_COLS            4


#define SIM_BAUD_RATE          115200


#define UART_TASK_DELAY        10
#define SIM_TASK_DELAY         100
#define INPUT_TASK_DELAY       50
#define HEARTBEAT_INTERVAL     5000


#define LCD_MESSAGE_TIMEOUT    2000


#define MAX_PACKET_SIZE        2048
#define MAX_PHONE_LENGTH       20
#define MAX_ID_LENGTH          10
#define MAX_MESSAGE_LENGTH     512

#define SYSTEM_NAME            "DO AN TOT NGHIEP"

#define ENABLE_DEBUG false

#define ACK_TIMEOUT_MS 5000

#define MAX_RETRY_COUNT 3

// ============================================
// BUTTON CONFIG
// ============================================

#define BUTTON_RECORD_PIN       18
#define BUTTON_SOS_PIN          19
#define BUTTON_DEBOUNCE_MS      200
#define RECORD_MAX_DURATION_MS  60000

#endif