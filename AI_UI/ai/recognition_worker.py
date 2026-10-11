import queue
import time
import traceback

from PyQt5.QtCore import QThread, pyqtSignal

from ai.asr_engine import get_recognizer, MicStream, transcribe_chunk, format_transcript
from ai.keyword_engine import KeywordEngine, evaluate
from core.state_manager import (
    state_manager
)

# Thời gian chờ cứng sau khi TTS kết thúc trước khi nhận lại mic.
# Phòng vẫn còn echo âm thanh từ loa trong khoảng này.
POST_TTS_COOLDOWN_S = 1.0   # demo: 1s; thực tế dùng 1.5s tránh echo phòng rộng

# Rolling context buffer — ghép các đoạn nói ngắn lại để bắt keyword bị cắt.
# Người già / trẻ em hay nói chậm, ngắt quãng: "đau..." (dừng) "...ngực"
ROLLING_WINDOW_S  = 8.0   # tăng 5→8s: người già nói chậm, từng từ một
ROLLING_MAX_WORDS = 30    # tăng 20→30: câu dài hơn sau khi ghép nhiều đoạn


def _is_tts_echo(text: str, sm) -> bool:
    """
    /**
     * Chức năng: Phát hiện echo TTS — kiểm tra xem văn bản ASR có phải là
     *            tiếng vang từ loa phát ra trong 10 giây vừa rồi hay không.
     * Tham số:
     *   - text : văn bản ASR vừa nhận diện được
     *   - sm   : StateManager chứa last_tts_text và last_tts_time
     * Trả về: True nếu nghi là echo TTS, False nếu không phải
     * Luồng hoạt động:
     *   1. Bỏ qua nếu không có TTS text gần đây.
     *   2. Bỏ qua nếu đã qua hơn 10 giây kể từ TTS cuối.
     *   3. Tính tỷ lệ từ trùng giữa ASR và TTS.
     *   4. Trả về True nếu tỷ lệ trùng >= 40%.
     */
    """
    if not sm.last_tts_text:
        return False
    if time.time() - sm.last_tts_time > 10.0:
        return False
    words_asr = set(text.lower().split())
    words_tts = set(sm.last_tts_text.lower().split())
    if not words_asr:
        return False
    overlap_ratio = len(words_asr & words_tts) / len(words_asr)
    return overlap_ratio >= 0.4


class RecognitionWorker(QThread):
    """
    Luồng nhận diện giọng nói chạy liên tục (24/7).

    Pipeline:
        MicStream (VAD) → audio_queue
        → transcribe_chunk (ASR)
        → echo detection / mic_muted check
        → rolling context buffer (ghép đoạn ngắn)
        → KeywordEngine.evaluate() + process()
        → result_signal → AIPage.on_result()

    Tự động khởi động lại khi gặp lỗi (_MAX_RESTARTS lần, do AIPage quản lý).
    """

    result_signal = pyqtSignal(dict)   # kết quả mỗi đoạn nhận diện (xem AIPage.on_result)
    log_signal    = pyqtSignal(str)    # log kỹ thuật → Panel 3 NHẬT KÝ HỆ THỐNG
    error_signal  = pyqtSignal(str)    # lỗi nghiêm trọng → trigger auto-restart
    status_signal = pyqtSignal(str)    # "RUNNING" | "ASR_OFFLINE" | "STOPPED"

    def __init__(
        self,
        parent=None
    ):
        """
        /**
         * Chức năng: Khởi tạo RecognitionWorker với trạng thái mặc định,
         *            hàng đợi audio và rolling context buffer rỗng.
         * Tham số:
         *   - parent : QObject cha (mặc định None)
         * Trả về: None
         * Luồng hoạt động:
         *   1. Gọi QThread.__init__().
         *   2. Khởi tạo cờ running = False.
         *   3. Tạo audio_queue để nhận chunk từ MicStream.
         *   4. Đặt mic và engine về None (chưa khởi tạo).
         *   5. Khởi tạo _context_buffer rỗng cho rolling window.
         */
        """

        super().__init__(parent)

        self.running = False

        self.audio_queue = queue.Queue()

        self.mic = None

        self.engine = None

        # Rolling context buffer: list of (timestamp, text)
        self._context_buffer: list = []

    def run(self):
        """
        /**
         * Chức năng: Vòng lặp chính của luồng nhận diện — khởi tạo ASR/mic,
         *            liên tục lấy audio chunk, nhận diện và xử lý keyword.
         * Tham số: Không (gọi bởi QThread.start())
         * Trả về: None
         * Luồng hoạt động:
         *   1. Khởi tạo ASR model, KeywordEngine và MicStream.
         *   2. Vòng lặp: lấy audio_chunk từ hàng đợi (timeout 0.5s).
         *   3. Bỏ qua nếu mic đang mute hoặc TTS đang phát.
         *   4. Nhận dạng giọng nói qua transcribe_chunk.
         *   5. Lọc echo TTS, đánh giá keyword, cập nhật rolling buffer.
         *   6. Gọi engine.process() nếu khớp keyword.
         *   7. Phát result_signal với kết quả đầy đủ ra giao diện.
         *   8. Gọi cleanup() khi vòng lặp kết thúc hoặc gặp lỗi.
         */
        """

        self.running = True

        state_manager.mic_enabled = True

        try:
            # Khởi tạo ASR model
            self.log_signal.emit("Đang khởi tạo ASR model...")
            get_recognizer()

            # Khởi tạo Keyword Engine
            self.log_signal.emit("Đang khởi tạo Keyword Engine...")
            self.engine = KeywordEngine()

            # Mở microphone
            self.log_signal.emit("Đang mở microphone...")
            self.mic = MicStream(result_queue=self.audio_queue)
            self.mic.start()

            self.log_signal.emit("Hệ thống đang lắng nghe...")
            self.status_signal.emit("RUNNING")

            _fail_streak = 0
            _OFFLINE_THRESHOLD = 3

            # Vòng lặp xử lý audio
            while self.running:
                try:
                    audio_chunk = self.audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Mic đang tạm tắt — bỏ chunk, không nhận diện
                if state_manager.mic_muted:
                    continue

                # Đo thời gian xử lý
                start_time = time.time()

                # Nhận dạng giọng nói
                try:
                    text = transcribe_chunk(audio_chunk)
                except Exception as e:
                    # Lỗi thực sự (mic ngắt, ONNX crash...) → tính vào fail_streak
                    _fail_streak += 1
                    if _fail_streak == _OFFLINE_THRESHOLD:
                        self.status_signal.emit("ASR_OFFLINE")
                    continue

                if not text:
                    # Model chạy bình thường nhưng không nhận ra gì
                    # (tiếng nền, noise, phòng yên tĩnh) — hoàn toàn bình thường
                    # với hệ thống 24/7. Không tính là lỗi, reset streak nếu đang có.
                    if _fail_streak > 0:
                        _fail_streak = 0
                    continue

                # Nhận dạng thành công — phục hồi nếu đang ở trạng thái offline
                if _fail_streak >= _OFFLINE_THRESHOLD:
                    self.status_signal.emit("RUNNING")
                _fail_streak = 0

                # 1. Chặn hoàn toàn khi loa đang phát
                if state_manager.tts_active:
                    continue

                # 2. Post-TTS cooldown cứng: chờ thêm 1.5s sau khi loa tắt
                #    vì phòng vẫn còn echo trong khoảng này
                if state_manager.last_tts_time > 0:
                    if time.time() - state_manager.last_tts_time < POST_TTS_COOLDOWN_S:
                        continue

                # 3. Đánh giá keyword trước — để bước 4 có thể giữ lại P0
                match = evaluate(text)

                # 4. Echo detection: bỏ qua nếu nghi là echo TTS trong 10s
                #    Ngoại lệ: P0 khẩn cấp vẫn cho qua dù trông như echo
                if _is_tts_echo(text, state_manager):
                    if match.matched and match.priority == 0:
                        self.log_signal.emit(
                            f"[TTS ECHO] P0 khẩn cấp — cho qua: '{text}'"
                        )
                    else:
                        self.log_signal.emit(
                            f"[TTS ECHO] Bỏ qua: '{text}'"
                        )
                        continue

                # 5. Rolling context buffer
                #    Thêm đoạn vừa nhận, loại entries cũ hơn ROLLING_WINDOW_S
                _now = time.time()
                self._context_buffer.append((_now, text))
                self._context_buffer = [
                    (t, s) for (t, s) in self._context_buffer
                    if _now - t <= ROLLING_WINDOW_S
                ]

                #    Nếu text đơn không khớp → thử ghép toàn bộ buffer
                if not match.matched and len(self._context_buffer) > 1:
                    _words = []
                    for _, s in self._context_buffer:
                        _words.extend(s.split())
                    _combined = " ".join(_words[-ROLLING_MAX_WORDS:])
                    _match_ctx = evaluate(_combined)
                    if _match_ctx.matched:
                        match = _match_ctx
                        self.log_signal.emit(
                            f"[CONTEXT] Ghép {len(self._context_buffer)} đoạn "
                            f"→ '{_combined}'"
                        )

                #    Match rồi → xóa buffer để tránh re-trigger liên tục
                if match.matched:
                    self._context_buffer.clear()

                sms_sent = False
                reason = "NO_MATCH"

                if match.matched:
                    # Emit log khi khớp keyword
                    priority_names = {0: "🚨 KHẨN CẤP",1: "🔴 NGUY HIỂM",2: "🟡 HỖ TRỢ",3: "🟢 NHU CẦU"}
                    priority_name = priority_names.get(match.priority, f"P{match.priority}")
                    log_msg = f"[MATCH] {priority_name} | {match.category} | Keyword: '{match.keyword}'"
                    self.log_signal.emit(log_msg)

                    sms_sent = self.engine.process(text, match=match)

                    if sms_sent:
                        reason = "SMS_SENT_OR_DRY_RUN"
                    else:
                        reason = "COOLDOWN_OR_SMS_FAILED"

                latency_ms = int((time.time() - start_time) * 1000)

                # Tạo event gửi sang giao diện
                event = {
                    "text": format_transcript(text),
                    "matched": match.matched,
                    "priority": match.priority,
                    "category": match.category,
                    "keyword": match.keyword,
                    "sms_sent": sms_sent,
                    "reason": reason,
                    "latency_ms": latency_ms,
                }

                self.result_signal.emit(event)

        except Exception as e:
            # Gửi thông báo lỗi chi tiết sang giao diện
            error_msg = f"Lỗi hệ thống: {str(e)}\n{traceback.format_exc()}"
            self.error_signal.emit(error_msg)

        finally:
            self.cleanup()

    def stop(self):
        """
        /**
         * Chức năng: Yêu cầu dừng vòng lặp nhận diện bằng cách tắt cờ running
         *            và đánh dấu mic đã tắt trong StateManager.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đặt self.running = False để thoát vòng while trong run().
         *   2. Cập nhật state_manager.mic_enabled = False.
         */
        """

        self.running = False

        state_manager.mic_enabled = False

    def cleanup(self):
        """
        /**
         * Chức năng: Giải phóng tài nguyên mic và engine sau khi vòng lặp kết thúc.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Dừng MicStream và đặt self.mic = None.
         *   2. Đóng KeywordEngine và đặt self.engine = None.
         *   3. Cập nhật state_manager.mic_enabled = False.
         *   4. Phát log_signal và status_signal "STOPPED".
         */
        """
        # Dừng microphone
        if self.mic is not None:
            try:
                self.mic.stop()
            except Exception as e:
                self.log_signal.emit(f"Lỗi khi dừng microphone: {e}")
            finally:
                self.mic = None

        # Đóng keyword engine
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception as e:
                self.log_signal.emit(f"Lỗi khi đóng Keyword Engine: {e}")
            finally:
                self.engine = None

        state_manager.mic_enabled = False

        self.log_signal.emit(
            "Hệ thống đã dừng."
        )

        self.status_signal.emit(
            "STOPPED"
        )
