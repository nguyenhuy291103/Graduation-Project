import os
import tempfile
import threading
import time
import logging

log = logging.getLogger("tts_service")

SMS_REPEAT_COUNT = 3    # Số lần lặp lại khi có tin nhắn đến
SMS_REPEAT_GAP_S = 2.0  # Khoảng nghỉ (giây) giữa các lần lặp


def _sleep_interruptible(duration_s: float, stop_event: threading.Event = None):
    """
    /**
     * Chức năng: Chờ duration_s giây với khả năng ngắt sớm khi stop_event
     *            được đặt — thay thế time.sleep() không thể ngắt.
     * Tham số:
     *   - duration_s  : tổng thời gian chờ (giây)
     *   - stop_event  : threading.Event để dừng sớm (None = không dùng)
     * Trả về: None
     * Luồng hoạt động:
     *   1. Chia duration thành các bước 50ms.
     *   2. Mỗi bước kiểm tra stop_event; thoát nếu đã được set.
     */
    """
    steps = int(duration_s / 0.05)
    for _ in range(steps):
        if stop_event and stop_event.is_set():
            break
        time.sleep(0.05)


def _play_once(stop_event: threading.Event = None):
    """
    /**
     * Chức năng: Phát một lần file nhạc đang được load trong pygame.mixer.music
     *            với âm lượng từ state_manager — không init/quit pygame.
     * Tham số:
     *   - stop_event : threading.Event để dừng sớm (None = không dùng)
     * Trả về: None
     * Luồng hoạt động:
     *   1. Đặt âm lượng theo speaker_volume trong StateManager.
     *   2. Kiểm tra stop_event trước khi phát.
     *   3. Phát file và chờ cho đến khi xong; dừng ngay nếu stop_event set.
     */
    """
    import pygame
    from core.state_manager import state_manager
    pygame.mixer.music.set_volume(
        max(0.0, min(1.0, state_manager.speaker_volume / 100.0))
    )
    if stop_event and stop_event.is_set():
        return
    pygame.mixer.music.play(0)   # loops=0 → phát đúng 1 lần
    while pygame.mixer.music.get_busy():
        if stop_event and stop_event.is_set():
            pygame.mixer.music.stop()
            break
        time.sleep(0.05)


def _speak_online(text: str, stop_event: threading.Event = None, repeat: int = 1) -> bool:
    """
    /**
     * Chức năng: Tổng hợp giọng nói bằng gTTS (online), lưu file MP3 tạm,
     *            và phát repeat lần qua pygame — init/quit pygame 1 lần.
     * Tham số:
     *   - text       : văn bản cần đọc
     *   - stop_event : threading.Event để dừng giữa chừng
     *   - repeat     : số lần lặp lại (mặc định 1)
     * Trả về: True nếu thành công, False nếu gTTS lỗi (để fallback offline)
     * Luồng hoạt động:
     *   1. Kiểm tra stop_event trước khi bắt đầu.
     *   2. Tạo file MP3 tạm và save bằng gTTS tiếng Việt.
     *   3. Init pygame, load file và phát repeat lần với khoảng nghỉ.
     *   4. Cleanup: quit pygame và xóa file tạm dù thành công hay lỗi.
     */
    """
    from gtts import gTTS
    import pygame

    if stop_event and stop_event.is_set():
        return True

    fd, tmp = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        gTTS(text=text, lang="vi").save(tmp)
    except Exception as e:
        log.warning(f"[TTS] gTTS lỗi khi tạo file: {e}")
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False

    try:
        pygame.mixer.init()
        pygame.mixer.music.load(tmp)
        for i in range(repeat):
            if stop_event and stop_event.is_set():
                break
            _play_once(stop_event)
            if i < repeat - 1 and not (stop_event and stop_event.is_set()):
                _sleep_interruptible(SMS_REPEAT_GAP_S, stop_event)
    except Exception as e:
        log.warning(f"[TTS] pygame lỗi: {e}")
    finally:
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        try:
            os.unlink(tmp)
        except Exception:
            pass

    return True


def _speak_offline(text: str, stop_event: threading.Event = None):
    """
    /**
     * Chức năng: Tổng hợp giọng nói offline bằng pyttsx3/SAPI5 —
     *            fallback khi mất mạng (giọng Anh, tiếng Việt không chuẩn).
     * Tham số:
     *   - text       : văn bản cần đọc
     *   - stop_event : threading.Event để dừng giữa chừng
     * Trả về: None
     * Luồng hoạt động:
     *   1. Kiểm tra stop_event trước khi bắt đầu.
     *   2. Khởi tạo pyttsx3 engine, đặt tốc độ và âm lượng.
     *   3. Chạy engine.runAndWait() trên thread riêng với done event.
     *   4. Chờ done với vòng lặp 50ms; dừng engine nếu stop_event set.
     */
    """
    if stop_event and stop_event.is_set():
        return
    from core.state_manager import state_manager
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 155)
        engine.setProperty(
            "volume",
            max(0.0, min(1.0, state_manager.speaker_volume / 100.0))
        )
        engine.say(text)

        done = threading.Event()

        def _run():
            try:
                engine.runAndWait()
            finally:
                done.set()

        threading.Thread(target=_run, daemon=True).start()

        while not done.wait(timeout=0.05):
            if stop_event and stop_event.is_set():
                try:
                    engine.stop()
                except Exception:
                    pass
                break

    except Exception as e:
        log.warning(f"[TTS] pyttsx3 fallback lỗi: {e}")


class TTSService:
    """
    Text-to-speech không chặn luồng chính.

    speak()     — đọc 1 lần (hướng dẫn, thông báo hệ thống).
    speak_sms() — đọc tin nhắn đến, lặp SMS_REPEAT_COUNT lần (mặc định 3).

    stop()      — dừng phát âm thanh hiện tại và hủy các lần lặp còn lại.
    """

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo TTSService với lock bảo vệ phát âm thanh tuần tự,
         *            đếm luồng đang hoạt động và stop_event.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tạo _speak_lock để đảm bảo chỉ một giọng phát tại một thời điểm.
         *   2. Tạo _count_lock để bảo vệ _active_count thread-safe.
         *   3. Khởi tạo _active_count = 0 và _stop_event chưa set.
         */
        """
        self._speak_lock  = threading.Lock()
        self._count_lock  = threading.Lock()
        self._active_count = 0
        self._stop_event  = threading.Event()

    # ─────────────────────────────────────────
    # PUBLIC
    # ─────────────────────────────────────────

    def speak(self, text: str):
        """
        /**
         * Chức năng: Đọc văn bản 1 lần (thông báo hệ thống, hướng dẫn).
         * Tham số:
         *   - text : văn bản cần đọc
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi _enqueue() với sms_mode=False và repeat=1.
         */
        """
        self._enqueue(text, sms_mode=False, repeat=1)

    def speak_sms(self, message: str):
        """
        /**
         * Chức năng: Đọc tin nhắn đến với tiền tố thông báo, lặp
         *            SMS_REPEAT_COUNT lần để đảm bảo người dùng nghe được.
         * Tham số:
         *   - message : nội dung tin nhắn cần đọc
         * Trả về: None
         * Luồng hoạt động:
         *   1. Ghép tiền tố "Bạn có tin nhắn mới..." vào message.
         *   2. Gọi _enqueue() với sms_mode=True và repeat=SMS_REPEAT_COUNT.
         */
        """
        full_text = (
            "Bạn có tin nhắn mới. "
            "Nội dung như sau. "
            f"{message}"
        )
        self._enqueue(full_text, sms_mode=True, repeat=SMS_REPEAT_COUNT)

    def stop(self):
        """
        /**
         * Chức năng: Dừng phát âm thanh hiện tại ngay lập tức và hủy
         *            các lần lặp còn lại trong hàng đợi.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Set _stop_event để báo hiệu dừng cho tất cả luồng TTS.
         *   2. Dừng pygame.mixer.music nếu đang chạy.
         */
        """
        self._stop_event.set()
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
        log.info("[TTS] Dừng theo yêu cầu")

    def is_playing(self) -> bool:
        """
        /**
         * Chức năng: Kiểm tra xem có luồng TTS nào đang phát không.
         * Tham số: Không
         * Trả về: True nếu đang phát, False nếu không
         * Luồng hoạt động:
         *   1. Lấy _count_lock và trả về _active_count > 0.
         */
        """
        with self._count_lock:
            return self._active_count > 0

    # ─────────────────────────────────────────
    # PRIVATE
    # ─────────────────────────────────────────

    def _enqueue(self, text: str, sms_mode: bool, repeat: int = 1):
        """
        /**
         * Chức năng: Khởi chạy luồng TTS mới (non-blocking) và cập nhật
         *            StateManager để RecognitionWorker biết đang phát TTS.
         * Tham số:
         *   - text     : văn bản cần đọc
         *   - sms_mode : True nếu là tin nhắn đến (cooldown dài hơn sau khi xong)
         *   - repeat   : số lần lặp lại
         * Trả về: None
         * Luồng hoạt động:
         *   1. Tăng _active_count (thread-safe).
         *   2. Cập nhật state_manager: tts_active=True, lưu text và timestamp.
         *   3. Start daemon thread chạy _speak_blocking().
         */
        """
        from core.state_manager import state_manager
        with self._count_lock:
            self._active_count += 1
        state_manager.tts_active = True
        state_manager.last_tts_text = text
        state_manager.last_tts_time = time.time()
        threading.Thread(
            target=self._speak_blocking,
            args=(text, sms_mode, repeat),
            daemon=True
        ).start()

    def _speak_blocking(self, text: str, sms_mode: bool, repeat: int):
        """
        /**
         * Chức năng: Phát giọng nói thực sự (blocking) trên daemon thread —
         *            thử online trước, fallback offline nếu gTTS thất bại.
         * Tham số:
         *   - text     : văn bản cần đọc
         *   - sms_mode : True nếu là tin nhắn đến (cooldown 3s thay vì 1s)
         *   - repeat   : số lần lặp lại
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy _speak_lock để đảm bảo chỉ một giọng phát tại một thời điểm.
         *   2. Clear _stop_event; thử _speak_online() với repeat lần.
         *   3. Nếu online thất bại: lặp _speak_offline() repeat lần với khoảng nghỉ.
         *   4. Cập nhật last_tts_time, chờ cooldown.
         *   5. Trong finally: giảm _active_count; nếu = 0 thì tắt tts_active.
         */
        """
        from core.state_manager import state_manager
        try:
            with self._speak_lock:
                self._stop_event.clear()

                ok = _speak_online(text, self._stop_event, repeat)

                if not ok:
                    # Fallback offline: lặp repeat lần
                    for i in range(repeat):
                        if self._stop_event.is_set():
                            break
                        _speak_offline(text, self._stop_event)
                        if i < repeat - 1 and not self._stop_event.is_set():
                            _sleep_interruptible(SMS_REPEAT_GAP_S, self._stop_event)

            state_manager.last_tts_time = time.time()
            cooldown = 3 if sms_mode else 1
            time.sleep(cooldown)
        finally:
            with self._count_lock:
                self._active_count -= 1
                if self._active_count == 0:
                    state_manager.tts_active = False


tts_service = TTSService()
