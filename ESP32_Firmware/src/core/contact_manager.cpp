#include "contact_manager.h"

// ============================================
// STORE
// ============================================

static ContactEntry contacts[MAX_CONTACTS];
static int contactCount = 0;
static SemaphoreHandle_t contactMutex = NULL;

// ============================================
// INIT
// ============================================

/**
 * Chức năng: Khởi tạo ContactManager — reset bộ đếm và tạo mutex bảo vệ.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Đặt contactCount = 0.
 *   2. Tạo FreeRTOS mutex để bảo vệ mảng contacts.
 */
void initContactManager()
{
    contactCount  = 0;
    contactMutex  = xSemaphoreCreateMutex();
}

// ============================================
// INTERNAL LOOKUP (gọi khi đang giữ mutex)
// ============================================

/**
 * Chức năng: Tìm chỉ số của liên hệ theo contactId trong mảng nội bộ.
 *            Phải gọi khi đang giữ contactMutex.
 * Tham số:
 *   - contactId : ID cần tìm
 * Trả về: chỉ số (>= 0) nếu tìm thấy, -1 nếu không
 * Luồng hoạt động:
 *   1. Duyệt tuyến tính qua mảng contacts[0..contactCount-1].
 *   2. Trả về chỉ số khi tìm thấy match, -1 nếu duyệt hết.
 */
static int findIndexById(const String& contactId)
{
    for (int i = 0; i < contactCount; i++)
    {
        if (contacts[i].contactId == contactId)
            return i;
    }
    return -1;
}

/**
 * Chức năng: Tìm chỉ số của liên hệ theo số điện thoại trong mảng nội bộ.
 *            Phải gọi khi đang giữ contactMutex.
 * Tham số:
 *   - phone : số điện thoại cần tìm
 * Trả về: chỉ số (>= 0) nếu tìm thấy, -1 nếu không
 * Luồng hoạt động:
 *   1. Duyệt tuyến tính qua mảng contacts[0..contactCount-1].
 *   2. Trả về chỉ số khi tìm thấy match, -1 nếu duyệt hết.
 */
static int findIndexByPhone(const String& phone)
{
    for (int i = 0; i < contactCount; i++)
    {
        if (contacts[i].phone == phone)
            return i;
    }
    return -1;
}

// ============================================
// SYNC (add or update)
// ============================================

/**
 * Chức năng: Đồng bộ một liên hệ — cập nhật nếu đã có theo ID,
 *            thêm mới nếu chưa có và còn chỗ.
 * Tham số:
 *   - contactId : ID duy nhất của liên hệ
 *   - phone     : số điện thoại
 *   - name      : tên liên hệ
 *   - relation  : quan hệ/vai trò
 * Trả về: void
 * Luồng hoạt động:
 *   1. Lấy contactMutex (timeout 100ms).
 *   2. Tìm entry theo ID: nếu có thì cập nhật phone/name/relation.
 *   3. Nếu chưa có và contactCount < MAX_CONTACTS: thêm entry mới.
 *   4. Trả mutex.
 */
void syncContact(
    const String& contactId,
    const String& phone,
    const String& name,
    const String& relation)
{
    if (contactMutex == NULL ||
        xSemaphoreTake(contactMutex,
            pdMS_TO_TICKS(100)) != pdTRUE)
        return;

    int idx = findIndexById(contactId);

    if (idx >= 0)
    {
        contacts[idx].phone    = phone;
        contacts[idx].name     = name;
        contacts[idx].relation = relation;
    }
    else if (contactCount < MAX_CONTACTS)
    {
        contacts[contactCount].contactId = contactId;
        contacts[contactCount].phone     = phone;
        contacts[contactCount].name      = name;
        contacts[contactCount].relation  = relation;
        contactCount++;
    }

    xSemaphoreGive(contactMutex);
}

// ============================================
// DELETE
// ============================================

/**
 * Chức năng: Xóa một liên hệ khỏi bộ nhớ theo contactId.
 * Tham số:
 *   - contactId : ID của liên hệ cần xóa
 * Trả về: void
 * Luồng hoạt động:
 *   1. Lấy contactMutex.
 *   2. Tìm entry; nếu thấy thì dịch các entry sau lên trước (shift-left).
 *   3. Giảm contactCount và trả mutex.
 */
void deleteContactLocal(const String& contactId)
{
    if (contactMutex == NULL ||
        xSemaphoreTake(contactMutex,
            pdMS_TO_TICKS(100)) != pdTRUE)
        return;

    int idx = findIndexById(contactId);

    if (idx >= 0)
    {
        for (int i = idx; i < contactCount - 1; i++)
            contacts[i] = contacts[i + 1];
        contactCount--;
    }

    xSemaphoreGive(contactMutex);
}

// ============================================
// CLEAR ALL
// ============================================

/**
 * Chức năng: Xóa toàn bộ danh sách liên hệ khỏi bộ nhớ.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Lấy contactMutex.
 *   2. Đặt contactCount = 0 (không cần xóa từng entry).
 *   3. Trả mutex.
 */
void clearAllContacts()
{
    if (contactMutex == NULL ||
        xSemaphoreTake(contactMutex,
            pdMS_TO_TICKS(100)) != pdTRUE)
        return;

    contactCount = 0;

    xSemaphoreGive(contactMutex);
}

// ============================================
// FIND NAME BY PHONE
// ============================================

/**
 * Chức năng: Tìm chuỗi hiển thị "relation name" của liên hệ theo SĐT —
 *            dùng để hiển thị tên người gửi trên LCD khi nhận SMS.
 * Tham số:
 *   - phone : số điện thoại cần tra cứu
 * Trả về: String "relation name" nếu tìm thấy, "" nếu không
 * Luồng hoạt động:
 *   1. Lấy contactMutex.
 *   2. Tìm entry theo phone.
 *   3. Ghép relation và name (nếu có) thành chuỗi kết quả.
 *   4. Trả mutex và trả chuỗi.
 */
String findNameByPhone(const String& phone)
{
    if (contactMutex == NULL ||
        xSemaphoreTake(contactMutex,
            pdMS_TO_TICKS(100)) != pdTRUE)
        return "";

    String result = "";
    int idx = findIndexByPhone(phone);

    if (idx >= 0)
    {
        if (contacts[idx].relation.length() > 0)
            result = contacts[idx].relation;

        if (contacts[idx].name.length() > 0)
        {
            if (result.length() > 0) result += " ";
            result += contacts[idx].name;
        }
    }

    xSemaphoreGive(contactMutex);
    return result;
}
