#include <Arduino.h>
#include <Keypad.h>

#include "config.h"
#include "system_state.h"
#include "packet.h"
#include "debug.h"

// ============================================
// EXTERNAL
// ============================================

extern void showLCDMessage(
    const String& line1,
    const String& line2);

extern void resetContactInput();

extern String buildAddContactPacket(
    const String& contactId,
    const String& phone);

extern String buildStartManualSMSPacket();

extern String buildStopManualSMSPacket();

extern String buildSOSPacket();

extern String buildStopAudioPacket();

extern void sendRawPacket(
    const String& packet);

// ============================================
// KEYPAD CONFIG
// ============================================

char keys[4][4] =
{
    {'1','2','3','A'},
    {'4','5','6','B'},
    {'7','8','9','C'},
    {'*','0','#','D'}
};

byte rowPins[4] = {13, 12, 14, 27};

byte colPins[4] = {26, 25, 33, 32};


Keypad keypad = Keypad(
    makeKeymap(keys),
    rowPins,
    colPins,
    KEYPAD_ROWS,
    KEYPAD_COLS);

// ============================================
// INIT
// ============================================

/**
 * Chức năng: Khởi tạo keypad ma trận 4x4 (hiện chỉ log vì thư viện
 *            Keypad.h tự cấu hình pin qua constructor).
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. In log "[KEYPAD] Initialized".
 */
void initKeypad()
{
    DEBUG_PRINTLN("[KEYPAD] Initialized");
}

// ============================================
// BUTTON STATE
// ============================================

static bool prevRecordBtn = HIGH;
static bool prevSOSBtn    = HIGH;
static unsigned long lastRecordDebounce = 0;
static unsigned long lastSOSDebounce    = 0;
static bool recordingActive             = false;
static unsigned long recordingStartTime = 0;

// ============================================
// INIT BUTTONS
// ============================================

/**
 * Chức năng: Cấu hình pin INPUT_PULLUP cho nút Record (B) và nút SOS.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Đặt BUTTON_RECORD_PIN và BUTTON_SOS_PIN thành INPUT_PULLUP.
 */
void initButtons()
{
    pinMode(BUTTON_RECORD_PIN, INPUT_PULLUP);
    pinMode(BUTTON_SOS_PIN,    INPUT_PULLUP);
    DEBUG_PRINTLN("[BUTTONS] Initialized");
}

// ============================================
// HANDLE BUTTONS
// ============================================

/**
 * Chức năng: Xử lý nút Record (B) và nút SOS với chống rung — phát lệnh
 *            UART tương ứng khi phát hiện cạnh xuống (HIGH→LOW).
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Đọc trạng thái nút Record; kiểm tra cạnh xuống với debounce.
 *      - Lần nhấn 1: bắt đầu ghi âm (START_MANUAL_SMS).
 *      - Lần nhấn 2: dừng ghi âm (STOP_MANUAL_SMS).
 *   2. Auto-stop ghi âm sau RECORD_MAX_DURATION_MS (1 phút).
 *   3. Đọc trạng thái nút SOS; phát SOS_ALERT nếu nhấn xuống.
 */
void handleButtons()
{
    unsigned long now = millis();

    // ----------------------------------------
    // RECORD BUTTON (GPIO 18)
    // ----------------------------------------

    bool currentRecord = digitalRead(BUTTON_RECORD_PIN);

    if (prevRecordBtn == HIGH && currentRecord == LOW)
    {
        if (now - lastRecordDebounce >= BUTTON_DEBOUNCE_MS)
        {
            lastRecordDebounce = now;

            if (!recordingActive)
            {
                recordingActive    = true;
                recordingStartTime = now;

                sendRawPacket(buildStartManualSMSPacket());
                showLCDMessage("RECORDING...", "PRESS TO SEND");
                DEBUG_PRINTLN("[RECORD] Started");
            }
            else
            {
                recordingActive = false;

                sendRawPacket(buildStopManualSMSPacket());
                showLCDMessage("MANUAL SMS", "SENDING...");
                DEBUG_PRINTLN("[RECORD] Stopped manually");
            }
        }
    }
    prevRecordBtn = currentRecord;

    // Auto-stop after 1 minute
    if (recordingActive && (now - recordingStartTime >= RECORD_MAX_DURATION_MS))
    {
        recordingActive = false;

        sendRawPacket(buildStopManualSMSPacket());
        showLCDMessage("AUTO SENT", "MAX 1 MIN");
        DEBUG_PRINTLN("[RECORD] Auto-stopped: 1 min limit");
    }

    // ----------------------------------------
    // SOS BUTTON (GPIO 19)
    // ----------------------------------------

    bool currentSOS = digitalRead(BUTTON_SOS_PIN);

    if (prevSOSBtn == HIGH && currentSOS == LOW)
    {
        if (now - lastSOSDebounce >= BUTTON_DEBOUNCE_MS)
        {
            lastSOSDebounce = now;

            sendRawPacket(buildSOSPacket());
            showLCDMessage("!!! SOS !!!", "ALERT SENT");
            DEBUG_PRINTLN("[SOS] Alert sent");
        }
    }
    prevSOSBtn = currentSOS;
}

// ============================================
// HANDLE INPUT SCREEN
// ============================================

/**
 * Chức năng: Cập nhật nội dung LCD theo trạng thái nhập liệu hiện tại
 *            (nhập ID hoặc nhập SĐT liên hệ).
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Nếu inputState == INPUT_CONTACT_ID: hiện "ADD ID: <currentContactId>".
 *   2. Nếu inputState == INPUT_CONTACT_PHONE: hiện "ADD PHONE: <currentContactPhone>".
 */
void updateInputLCD()
{
    if (systemState.inputState ==
        INPUT_CONTACT_ID)
    {
        systemState.lcdLine1 = "ADD ID:";
        systemState.lcdLine2 =
            systemState.currentContactId;
    }
    else if (systemState.inputState ==
             INPUT_CONTACT_PHONE)
    {
        systemState.lcdLine1 = "ADD PHONE:";
        systemState.lcdLine2 =
            systemState.currentContactPhone;
    }
}

// ============================================
// HANDLE KEYPAD
// ============================================

/**
 * Chức năng: Xử lý phím nhấn từ keypad 4x4 — điều hướng luồng nhập liệu
 *            liên hệ và các phím chức năng đặc biệt.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Đọc phím từ keypad; thoát ngay nếu không có phím nào.
 *   2. Phím A: gửi STOP_AUDIO lên Python và hiện thông báo LCD.
 *   3. Phím D: bắt đầu nhập ID liên hệ mới.
 *   4. Phím #: xóa ký tự cuối trong trường đang nhập (backspace).
 *   5. Phím *: chuyển bước nhập ID → SĐT, hoặc lưu liên hệ khi SĐT hợp lệ.
 *   6. Phím C: hủy nhập liên hệ, về INPUT_IDLE.
 *   7. Số 0-9: thêm chữ số vào trường ID hoặc SĐT đang nhập.
 */
void handleKeypad()
{
    char key = keypad.getKey();

    if (!key)
    {
        return;
    }

    DEBUG_PRINT("[KEYPAD] ");
    DEBUG_PRINTLN(key);

    // ========================================
    // STOP AUDIO (key A)
    // Gửi lệnh dừng TTS lên Python.
    // Python chỉ thực sự dừng nếu đang phát — nếu không thì silent no-op.
    // ========================================

    if (key == 'A')
    {
        sendRawPacket(buildStopAudioPacket());
        showLCDMessage("DUNG AM THANH", "");
        DEBUG_PRINTLN("[KEYPAD] STOP AUDIO");
        return;
    }

    // ========================================
    // START ADD CONTACT
    // ========================================

    if (key == 'D')
    {
        resetContactInput();

        systemState.inputState =
            INPUT_CONTACT_ID;

        updateInputLCD();

        return;
    }

    // ========================================
    // BACKSPACE
    // ========================================

    if (key == '#')
    {
        if (systemState.inputState ==
            INPUT_CONTACT_ID)
        {
            if (systemState.currentContactId.length() > 0)
            {
                systemState.currentContactId.remove(
                    systemState.currentContactId.length() - 1);
            }
        }
        else if (systemState.inputState ==
                 INPUT_CONTACT_PHONE)
        {
            if (systemState.currentContactPhone.length() > 0)
            {
                systemState.currentContactPhone.remove(
                    systemState.currentContactPhone.length() - 1);
            }
        }

        updateInputLCD();

        return;
    }

    // ========================================
    // NEXT / SAVE
    // ========================================

    if (key == '*')
    {
        // NEXT TO PHONE
        if (systemState.inputState ==
            INPUT_CONTACT_ID)
        {
            if (systemState.currentContactId.length() == 0)
            {
                return;
            }

            systemState.inputState =
                INPUT_CONTACT_PHONE;

            updateInputLCD();

            return;
        }

        // SAVE CONTACT
        if (systemState.inputState ==
            INPUT_CONTACT_PHONE)
        {
            if (systemState.currentContactPhone.length() == 0)
            {
                return;
            }

            String phone = systemState.currentContactPhone;
            bool phoneValid = (phone.length() == 10 && phone.charAt(0) == '0');
            for (int i = 0; i < (int)phone.length() && phoneValid; i++)
            {
                if (!isdigit(phone.charAt(i))) phoneValid = false;
            }
            if (!phoneValid)
            {
                showLCDMessage("PHONE INVALID", "TRY AGAIN");
                return;
            }

            String packet =
                buildAddContactPacket(
                    systemState.currentContactId,
                    systemState.currentContactPhone);

            sendRawPacket(packet);

            showLCDMessage(
                "CONTACT SENT",
                "WAIT RESPONSE");

            resetContactInput();

            return;
        }
    }

    // ========================================
    // CANCEL ADD CONTACT (key C)
    // ========================================

    if (key == 'C')
    {
        if (systemState.inputState == INPUT_CONTACT_ID ||
            systemState.inputState == INPUT_CONTACT_PHONE)
        {
            resetContactInput();

            systemState.inputState = INPUT_IDLE;

            showLCDMessage(
                "CANCELLED",
                "ADD CONTACT");
        }

        return;
    }

    // ========================================
    // NUMBER INPUT
    // ========================================

    if (isdigit(key))
    {
        if (systemState.inputState ==
            INPUT_CONTACT_ID)
        {
            if (systemState.currentContactId.length()
                < MAX_ID_LENGTH)
            {
                systemState.currentContactId += key;
            }
        }
        else if (systemState.inputState ==
                 INPUT_CONTACT_PHONE)
        {
            if (systemState.currentContactPhone.length()
                < MAX_PHONE_LENGTH)
            {
                systemState.currentContactPhone += key;
            }
        }

        updateInputLCD();
    }
}
