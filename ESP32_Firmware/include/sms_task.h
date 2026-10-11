#ifndef SMS_TASK_H
#define SMS_TASK_H

/**
 * Chức năng: Task FreeRTOS chạy trên Core 0 — lấy SMSJob từ smsQueue
 *            và gọi sendSMS() để gửi từng tin nhắn tuần tự.
 * Tham số:
 *   - parameter : con trỏ tham số FreeRTOS (không dùng)
 * Trả về: void (task loop vô tận)
 */
void smsTask(
    void* parameter
);

#endif
