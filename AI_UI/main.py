import sys

from PyQt5.QtWidgets import (
    QApplication,
    QMessageBox
)

from ui.main_window import (
    MainWindow
)

from core.state_manager import (
    state_manager
)

from services.database_service import (
    database_service
)


# =====================================
# GLOBAL EXCEPTION
# =====================================

def exception_hook(
    exc_type,
    exc_value,
    exc_traceback
):
    """
    /**
     * Chức năng: Bắt mọi ngoại lệ chưa được xử lý trong ứng dụng Qt và
     *            hiển thị hộp thoại lỗi trước khi chuyển sang hook gốc.
     * Tham số:
     *   - exc_type      : kiểu ngoại lệ (class Exception)
     *   - exc_value     : giá trị / thông điệp ngoại lệ
     *   - exc_traceback : traceback của ngoại lệ
     * Trả về: None
     * Luồng hoạt động:
     *   1. Tạo chuỗi thông báo từ tên kiểu và giá trị ngoại lệ.
     *   2. Hiện hộp thoại lỗi nghiêm trọng cho người dùng.
     *   3. Gọi lại hook ngoại lệ mặc định của Python để in traceback.
     */
    """
    error_message = (
        f"{exc_type.__name__}\n\n"
        f"{exc_value}"
    )

    QMessageBox.critical(
        None,
        "SYSTEM ERROR",
        error_message
    )

    sys.__excepthook__(
        exc_type,
        exc_value,
        exc_traceback
    )


# =====================================
# INIT SYSTEM
# =====================================

def initialize_system():
    """
    /**
     * Chức năng: Khởi tạo các thành phần cốt lõi của hệ thống trước khi
     *            cửa sổ Qt được tạo (database, trạng thái audio mặc định).
     * Tham số: Không
     * Trả về: None
     * Luồng hoạt động:
     *   1. Khởi tạo database — tạo bảng nếu chưa có.
     *   2. Đặt trạng thái mic mặc định là tắt.
     *   3. Đặt âm lượng loa mặc định là 70%.
     */
    """

    # ================================
    # DATABASE
    # ================================

    try:

        database_service.initialize()

        print(
            "[SYSTEM] Database Ready"
        )

    except Exception as error:

        print(
            "[SYSTEM] Database Error:",
            error
        )

    # ================================
    # MICROPHONE
    # ================================

    state_manager.mic_enabled = False

    state_manager.speaker_volume = 70


# =====================================
# MAIN
# =====================================

def main():
    """
    /**
     * Chức năng: Điểm vào chính của ứng dụng — cài hook ngoại lệ, khởi tạo
     *            hệ thống, tạo ứng dụng Qt và chạy vòng lặp sự kiện.
     * Tham số: Không
     * Trả về: None (thoát qua sys.exit)
     * Luồng hoạt động:
     *   1. Đăng ký exception_hook toàn cục để bắt lỗi Qt.
     *   2. Gọi initialize_system() khởi tạo database và audio.
     *   3. Tạo QApplication với style Fusion.
     *   4. Tạo và hiển thị MainWindow.
     *   5. Chạy vòng lặp sự kiện Qt, thoát khi cửa sổ đóng.
     */
    """

    sys.excepthook = exception_hook

    # ================================
    # INIT SYSTEM
    # ================================

    initialize_system()

    # ================================
    # QT APPLICATION
    # ================================

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        "AI Emergency System"
    )

    app.setStyle(
        "Fusion"
    )

    # ================================
    # MAIN WINDOW
    # ================================

    window = MainWindow()

    window.show()

    # ================================
    # RUN
    # ================================

    sys.exit(
        app.exec_()
    )


# =====================================
# START
# =====================================

if __name__ == "__main__":

    main()
