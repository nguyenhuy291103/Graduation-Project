#include "ack_manager.h"
#include "config.h"
#include "debug.h"

static PendingPacket pendingPackets[MAX_PENDING_PACKETS];

static int pendingCount = 0;

static SemaphoreHandle_t ackMutex = NULL;

extern void sendRawPacket(const String& packet);

// =========================================
// INIT
// =========================================

/**
 * Chức năng: Khởi tạo AckManager — reset bộ đệm pending và tạo mutex
 *            bảo vệ truy cập đa luồng.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Đặt pendingCount = 0.
 *   2. Tạo FreeRTOS mutex; log lỗi nếu thất bại.
 */
void initAckManager()
{
    pendingCount = 0;

    ackMutex = xSemaphoreCreateMutex();

    if (ackMutex == NULL)
    {
        DEBUG_PRINTLN("[ACK] Mutex create failed");
    }
}

// =========================================
// REMOVE ACKNOWLEDGED (phải giữ ackMutex trước khi gọi)
// =========================================

/**
 * Chức năng: Dồn mảng pendingPackets về phía trước, xóa tất cả entry
 *            đã được ACK. Phải gọi khi đang giữ ackMutex.
 * Tham số: Không
 * Trả về: void (static — chỉ dùng nội bộ)
 * Luồng hoạt động:
 *   1. Duyệt mảng; copy các entry chưa ACK sang đầu mảng (in-place compact).
 *   2. Cập nhật pendingCount.
 */
static void removeAcknowledgedPackets()
{
    int writeIndex = 0;

    for (int i = 0; i < pendingCount; i++)
    {
        if (!pendingPackets[i].acknowledged)
        {
            pendingPackets[writeIndex] = pendingPackets[i];
            writeIndex++;
        }
    }

    pendingCount = writeIndex;

    DEBUG_PRINT("[ACK] Pending = ");
    DEBUG_PRINTLN(pendingCount);
}

// =========================================
// ADD
// =========================================

/**
 * Chức năng: Thêm một gói tin vào hàng đợi pending để theo dõi ACK.
 * Tham số:
 *   - packetId   : ID duy nhất của gói tin
 *   - packetData : nội dung JSON thô để gửi lại khi timeout
 * Trả về: void
 * Luồng hoạt động:
 *   1. Bỏ qua nếu packetId rỗng.
 *   2. Lấy ackMutex; bỏ qua nếu buffer đầy.
 *   3. Thêm entry mới với timestamp hiện tại, acknowledged=false, retryCount=0.
 *   4. Tăng pendingCount và trả mutex.
 */
void addPendingPacket(
    const String& packetId,
    const String& packetData)
{
    if (packetId.length() == 0)
    {
        return;
    }

    if (ackMutex == NULL ||
        xSemaphoreTake(ackMutex, pdMS_TO_TICKS(100)) != pdTRUE)
    {
        return;
    }

    if (pendingCount >= MAX_PENDING_PACKETS)
    {
        DEBUG_PRINTLN("[ACK] BUFFER FULL");
        xSemaphoreGive(ackMutex);
        return;
    }

    pendingPackets[pendingCount].packetId     = packetId;
    pendingPackets[pendingCount].packetData   = packetData;
    pendingPackets[pendingCount].timestamp    = millis();
    pendingPackets[pendingCount].acknowledged = false;
    pendingPackets[pendingCount].retryCount   = 0;

    DEBUG_PRINT("[ACK ADD] ");
    DEBUG_PRINTLN(packetId);

    pendingCount++;

    xSemaphoreGive(ackMutex);
}

// =========================================
// ACK
// =========================================

/**
 * Chức năng: Đánh dấu một gói tin đã được ACK và dọn dẹp ngay khỏi buffer.
 * Tham số:
 *   - packetId : ID của gói tin đã nhận được ACK
 * Trả về: void
 * Luồng hoạt động:
 *   1. Lấy ackMutex.
 *   2. Tìm entry khớp packetId và đặt acknowledged = true.
 *   3. Gọi removeAcknowledgedPackets() để compact mảng.
 *   4. Trả mutex.
 */
void acknowledgePacket(
    const String& packetId)
{
    if (ackMutex == NULL ||
        xSemaphoreTake(ackMutex, pdMS_TO_TICKS(100)) != pdTRUE)
    {
        return;
    }

    for (int i = 0; i < pendingCount; i++)
    {
        if (pendingPackets[i].packetId == packetId)
        {
            pendingPackets[i].acknowledged = true;

            DEBUG_PRINT("[ACK RX] ");
            DEBUG_PRINTLN(packetId);

            break;
        }
    }

    removeAcknowledgedPackets();

    xSemaphoreGive(ackMutex);
}

// =========================================
// TIMEOUT + RETRY
// =========================================

/**
 * Chức năng: Kiểm tra tất cả gói đang chờ ACK — gửi lại nếu quá timeout,
 *            bỏ cuộc nếu đã hết số lần retry.
 * Tham số: Không
 * Trả về: void
 * Luồng hoạt động:
 *   1. Lấy ackMutex.
 *   2. Duyệt mảng; bỏ qua entry đã ACK.
 *   3. Nếu millis() - timestamp > ACK_TIMEOUT_MS:
 *      a. Nếu retryCount < MAX_RETRY_COUNT: tăng retry, cập nhật timestamp,
 *         gọi sendRawPacket() để gửi lại.
 *      b. Ngược lại: đánh dấu acknowledged (bỏ cuộc).
 *   4. Gọi removeAcknowledgedPackets() và trả mutex.
 */
void checkPacketTimeouts()
{
    if (ackMutex == NULL ||
        xSemaphoreTake(ackMutex, pdMS_TO_TICKS(100)) != pdTRUE)
    {
        return;
    }

    unsigned long now = millis();

    for (int i = 0; i < pendingCount; i++)
    {
        if (pendingPackets[i].acknowledged)
        {
            continue;
        }

        if (now - pendingPackets[i].timestamp > ACK_TIMEOUT_MS)
        {
            if (pendingPackets[i].retryCount < MAX_RETRY_COUNT &&
                pendingPackets[i].packetData.length() > 0)
            {
                pendingPackets[i].retryCount++;
                pendingPackets[i].timestamp = now;

                DEBUG_PRINT("[ACK RETRY] ");
                DEBUG_PRINT(pendingPackets[i].packetId);
                DEBUG_PRINT(" attempt=");
                DEBUG_PRINTLN(pendingPackets[i].retryCount);

                sendRawPacket(pendingPackets[i].packetData);
            }
            else
            {
                DEBUG_PRINT("[ACK GIVE UP] ");
                DEBUG_PRINTLN(pendingPackets[i].packetId);

                pendingPackets[i].acknowledged = true;
            }
        }
    }

    removeAcknowledgedPackets();

    xSemaphoreGive(ackMutex);
}
