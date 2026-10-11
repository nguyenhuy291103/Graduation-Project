#ifndef CONTACT_MANAGER_H
#define CONTACT_MANAGER_H

#include <Arduino.h>

#define MAX_CONTACTS 50

struct ContactEntry
{
    String contactId;
    String phone;
    String name;
    String relation;
};

/**
 * Chức năng: Khởi tạo ContactManager — xóa toàn bộ bảng liên hệ local.
 * Tham số: Không
 * Trả về: void
 */
void initContactManager();

/**
 * Chức năng: Thêm hoặc cập nhật liên hệ theo contactId trong bảng local.
 * Tham số:
 *   - contactId : ID định danh liên hệ (duy nhất)
 *   - phone     : số điện thoại
 *   - name      : tên hiển thị
 *   - relation  : quan hệ với người dùng
 * Trả về: void
 */
void syncContact(
    const String& contactId,
    const String& phone,
    const String& name,
    const String& relation);

/**
 * Chức năng: Xóa liên hệ theo contactId khỏi bảng local.
 * Tham số:
 *   - contactId : ID liên hệ cần xóa
 * Trả về: void
 */
void deleteContactLocal(const String& contactId);

/**
 * Chức năng: Xóa toàn bộ danh bạ local (dùng trước khi sync lại từ Python).
 * Tham số: Không
 * Trả về: void
 */
void clearAllContacts();

/**
 * Chức năng: Tìm tên hiển thị liên hệ theo số điện thoại.
 * Tham số:
 *   - phone : số điện thoại cần tra cứu
 * Trả về: String tên liên hệ, hoặc "" nếu không tìm thấy
 */
String findNameByPhone(const String& phone);

#endif
