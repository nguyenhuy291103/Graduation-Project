#include "system_state.h"
#include "debug.h"

extern void sendSMS(
    const String& packetId,
    const String& phone,
    const String& message,
    int priority,
    const String& category
);

/**
 * Chức năng: Task FreeRTOS xử lý hàng đợi SMS — nhận SMSJob từ smsQueue
 *            và gọi sendSMS() tuần tự để tránh tranh chấp module SIM.
 * Tham số:
 *   - parameter : con trỏ tham số FreeRTOS (không dùng)
 * Trả về: void (task chạy vĩnh viễn hoặc tự xóa nếu queue null)
 * Luồng hoạt động:
 *   1. Kiểm tra smsQueue hợp lệ; tự xóa task nếu null.
 *   2. Vòng lặp: chờ blocking trên xQueueReceive(portMAX_DELAY).
 *   3. Khi nhận được SMSJob: gọi sendSMS() với thông tin từ job.
 */
void smsTask(
    void* parameter
)
{
    if (smsQueue == nullptr)
    {
        Serial.println("[SMS TASK] Queue null — exiting");
        vTaskDelete(NULL);
        return;
    }

    SMSJob job;

    while(true)
    {
        if(
            xQueueReceive(
                smsQueue,
                &job,
                portMAX_DELAY
            ) == pdTRUE
        )
        {
            DEBUG_PRINTLN(
                "[SMS TASK] NEW JOB"
            );

            sendSMS(
                String(job.packetId),
                String(job.phone),
                String(job.message),
                job.priority,
                String(job.category)
            );
        }
    }
}
