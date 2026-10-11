"""
asr_engine.py
─────────────
ASR module: mic streaming liên tục → text (tiếng Việt)
- Model ASR : gipformer-65M-rnnt (Zipformer Transducer)
- VAD       : Silero VAD v5 (ưu tiên) | Energy-based (fallback)
- Backend   : sherpa-onnx (ONNX Runtime)

Lần đầu chạy tự download model từ HuggingFace về cache.
"""

import os
import queue
import re
import threading
import time
from collections import deque
from typing import Optional
import numpy as np
import sounddevice as sd

try:
    import sherpa_onnx
except ImportError:
    raise ImportError("Thiếu sherpa-onnx. Chạy: pip install sherpa-onnx")

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    raise ImportError("Thiếu huggingface_hub. Chạy: pip install huggingface_hub")

try:
    from silero_vad import load_silero_vad, VADIterator
    import torch
    _SILERO_AVAILABLE = True
except ImportError:
    _SILERO_AVAILABLE = False


# ─────────────────────────────────────────────────────────
# CẤU HÌNH ASR
# ─────────────────────────────────────────────────────────

REPO_ID      = "g-group-ai-lab/gipformer-65M-rnnt"
QUANTIZE     = "int8"
NUM_THREADS  = 4
SAMPLE_RATE  = 16000
FEATURE_DIM  = 80

MIN_SPEECH_MS = 200   # đoạn ngắn hơn 200ms → bỏ (noise/click)

_MIC_DEVICE_PREFERRED = 1

def _resolve_mic_device(preferred: int) -> object:
    """
    /**
     * Chức năng: Trả về preferred device index nếu tồn tại, ngược lại trả None
     *            để dùng system default mic.
     * Tham số:
     *   preferred : chỉ số device mic ưu tiên
     * Trả về: int device index hoặc None
     * Luồng hoạt động:
     *   1. Query danh sách device qua sounddevice.
     *   2. Nếu preferred hợp lệ: trả về preferred.
     *   3. Ngược lại: in cảnh báo và trả None.
     */
    """
    try:
        devices = sd.query_devices()
        if preferred is not None and preferred < len(devices):
            return preferred
    except Exception:
        pass
    print(f"[MIC] Device {preferred} không tìm thấy — dùng system default.")
    return None

MIC_DEVICE = _resolve_mic_device(_MIC_DEVICE_PREFERRED)


# ─────────────────────────────────────────────────────────
# CẤU HÌNH SILERO VAD
# ─────────────────────────────────────────────────────────

SILERO_CHUNK          = 512   # samples bắt buộc (32ms @ 16 kHz)
SILERO_THRESHOLD      = 0.45  # giảm nhẹ → nhạy hơn với giọng người già/trẻ em yếu
SILERO_MIN_SILENCE_MS = 600   # demo: 600ms phản hồi nhanh; người thực tế dùng: 800ms
SILERO_PAD_MS         = 50    # tăng nhẹ → giữ lại âm đuôi câu
SILERO_PRE_CHUNKS     = 4     # tăng pre-buffer: bắt đầu câu sớm hơn ~128ms


# ─────────────────────────────────────────────────────────
# CẤU HÌNH ENERGY VAD (fallback)
# ─────────────────────────────────────────────────────────

ENERGY_CHUNK_MS  = 200
SILENCE_MS       = 900
MAX_BUFFER_S     = 12
ENERGY_THRESHOLD = 0.01   # giảm → nhạy hơn | tăng → ít noise hơn

AUDIO_TARGET_RMS = 0.08
AUDIO_MAX_GAIN   = 20.0   # giới hạn gain tối đa 20x (~26 dB)


# ─────────────────────────────────────────────────────────
# TÊN FILE ONNX TRÊN HUGGINGFACE (ASR)
# ─────────────────────────────────────────────────────────

_ONNX_FILES = {
    "int8": {
        "encoder": "encoder-epoch-35-avg-6.int8.onnx",
        "decoder": "decoder-epoch-35-avg-6.int8.onnx",
        "joiner":  "joiner-epoch-35-avg-6.int8.onnx",
    },
    "fp32": {
        "encoder": "encoder-epoch-35-avg-6.onnx",
        "decoder": "decoder-epoch-35-avg-6.onnx",
        "joiner":  "joiner-epoch-35-avg-6.onnx",
    },
}


# ─────────────────────────────────────────────────────────
# DOWNLOAD MODEL ASR
# ─────────────────────────────────────────────────────────

def _download_model(quantize: str = QUANTIZE) -> dict:
    """
    /**
     * Chức năng: Download (hoặc lấy từ cache) các file ONNX của model ASR
     *            từ HuggingFace Hub về thư mục cache local.
     * Tham số:
     *   quantize : loại quantization ("int8" hoặc "fp32")
     * Trả về: dict với keys encoder/decoder/joiner/tokens → đường dẫn local
     * Luồng hoạt động:
     *   1. Lấy danh sách filename theo quantize từ _ONNX_FILES.
     *   2. Download từng file (encoder, decoder, joiner) qua hf_hub_download.
     *   3. Download tokens.txt.
     *   4. Trả về dict paths.
     */
    """
    files = _ONNX_FILES[quantize]
    print(f"[ASR] Checking/downloading model '{quantize}' từ {REPO_ID} ...")
    paths = {}
    for key, filename in files.items():
        paths[key] = hf_hub_download(repo_id=REPO_ID, filename=filename)
    paths["tokens"] = hf_hub_download(repo_id=REPO_ID, filename="tokens.txt")
    print("[ASR] Model files sẵn sàng.")
    return paths


# ─────────────────────────────────────────────────────────
# RECOGNIZER (singleton)
# ─────────────────────────────────────────────────────────

_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None


_HOTWORDS_FILE = os.path.join(os.path.dirname(__file__), "hotwords.txt")
_HOTWORDS_SCORE = 10.0   # bias boost cho các từ khẩn cấp (5–20, cao hơn → ưu tiên hơn)


def get_recognizer() -> sherpa_onnx.OfflineRecognizer:
    """
    /**
     * Chức năng: Trả về singleton OfflineRecognizer — khởi tạo lần đầu nếu chưa có,
     *            bao gồm download model, load hotwords và warm-up inference.
     * Tham số: Không
     * Trả về: sherpa_onnx.OfflineRecognizer đã sẵn sàng
     * Luồng hoạt động:
     *   1. Nếu _recognizer đã tồn tại: trả về ngay.
     *   2. Download model files qua _download_model().
     *   3. Load hotwords.txt nếu tồn tại (hotword boosting).
     *   4. Tạo OfflineRecognizer với modified_beam_search, max_active_paths=8.
     *   5. Warm-up: chạy inference 1s silence để ONNX JIT-compile lần đầu.
     */
    """
    global _recognizer
    if _recognizer is None:
        t0    = time.time()
        paths = _download_model(QUANTIZE)

        hotwords_file  = _HOTWORDS_FILE if os.path.isfile(_HOTWORDS_FILE) else ""
        hotwords_score = _HOTWORDS_SCORE if hotwords_file else 1.0
        if hotwords_file:
            print(f"[ASR] Hotword boosting ON — score={hotwords_score}")
        else:
            print("[ASR] Hotword boosting OFF (không tìm thấy hotwords.txt)")

        _recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=paths["encoder"],
            decoder=paths["decoder"],
            joiner=paths["joiner"],
            tokens=paths["tokens"],
            num_threads=NUM_THREADS,
            sample_rate=SAMPLE_RATE,
            feature_dim=FEATURE_DIM,
            decoding_method="modified_beam_search",
            max_active_paths=8,
            hotwords_file=hotwords_file,
            hotwords_score=hotwords_score,
        )
        print(f"[ASR] Recognizer khởi tạo xong sau {time.time() - t0:.1f}s")

        # Warm-up: inference 1 giây silence để ONNX Runtime JIT-compile lần đầu
        _wu = _recognizer.create_stream()
        _wu.accept_waveform(SAMPLE_RATE, np.zeros(SAMPLE_RATE, dtype=np.float32))
        _recognizer.decode_stream(_wu)
        print("[ASR] Warm-up xong — sẵn sàng nhận diện")

    return _recognizer


# ─────────────────────────────────────────────────────────
# TRANSCRIBE
# ─────────────────────────────────────────────────────────

def transcribe_chunk(audio: np.ndarray) -> Optional[str]:
    """
    /**
     * Chức năng: Nhận diện giọng nói từ mảng audio numpy float32 → trả về text tiếng Việt.
     * Tham số:
     *   audio : mảng numpy float32 mono @ 16kHz
     * Trả về: str kết quả nhận diện, hoặc None nếu quá ngắn/trống
     * Luồng hoạt động:
     *   1. Lọc đoạn ngắn hơn MIN_SPEECH_MS (noise/click).
     *   2. Lấy recognizer singleton; tạo stream mới.
     *   3. Tiền xử lý audio qua _preprocess_audio().
     *   4. Decode stream và lấy result.text.
     *   5. Trả None nếu text rỗng, ngược lại trả text và log latency.
     */
    """
    duration_ms = len(audio) / SAMPLE_RATE * 1000
    if duration_ms < MIN_SPEECH_MS:
        return None

    recognizer = get_recognizer()
    t0 = time.time()

    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, _preprocess_audio(audio))
    recognizer.decode_stream(stream)

    result     = stream.result.text.strip()
    latency_ms = (time.time() - t0) * 1000

    if not result:
        return None

    print(f"[ASR] '{result}'  ({latency_ms:.0f}ms, dur={duration_ms:.0f}ms)")
    return result


# ─────────────────────────────────────────────────────────
# ENERGY VAD (fallback)
# ─────────────────────────────────────────────────────────

def _is_speech(chunk: np.ndarray) -> bool:
    """
    /**
     * Chức năng: Phát hiện giọng nói bằng ngưỡng RMS đơn giản (Energy VAD fallback).
     * Tham số:
     *   chunk : mảng numpy float32 audio cần kiểm tra
     * Trả về: True nếu RMS vượt ngưỡng ENERGY_THRESHOLD
     * Luồng hoạt động:
     *   1. Tính RMS của chunk.
     *   2. So sánh với ENERGY_THRESHOLD và trả kết quả.
     */
    """
    rms = float(np.sqrt(np.mean(chunk ** 2)))
    return rms > ENERGY_THRESHOLD


# ─────────────────────────────────────────────────────────
# AUDIO PREPROCESSING
# ─────────────────────────────────────────────────────────

def _preprocess_audio(audio: np.ndarray) -> np.ndarray:
    """
    /**
     * Chức năng: Tiền xử lý audio trước khi đưa vào model ASR.
     * Tham số:
     *   audio : mảng numpy float32 mono @ 16kHz thô từ mic
     * Trả về: mảng numpy float32 đã được chuẩn hóa, clip [-1, 1]
     * Luồng hoạt động:
     *   1. Bỏ DC offset (trừ mean).
     *   2. Normalize RMS lên AUDIO_TARGET_RMS (giới hạn AUDIO_MAX_GAIN).
     *   3. Clip [-1, 1].
     */
    """
    audio = audio - np.mean(audio)
    rms   = float(np.sqrt(np.mean(audio ** 2)))
    if rms > 1e-4:
        gain  = min(AUDIO_TARGET_RMS / rms, AUDIO_MAX_GAIN)
        audio = audio * gain
    return np.clip(audio, -1.0, 1.0)


# ─────────────────────────────────────────────────────────
# FORMAT TRANSCRIPT (chỉ dùng hiển thị — không ảnh hưởng keyword matching)
# ─────────────────────────────────────────────────────────

SENTENCE_ENDINGS = ".!?"

QUESTION_HINTS = (
    "không", "khong", "ở đâu", "o dau", "đâu", "dau",
    "ai", "sao", "tại sao", "tai sao",
)

URGENT_HINTS = (
    "cứu", "cuu", "cháy", "chay",
    "khó thở", "kho tho", "ngộp", "ngop", "ngạt", "ngat",
    "đau ngực", "dau nguc",
)


def format_transcript(text: str) -> str:
    """
    /**
     * Chức năng: Định dạng text ASR để hiển thị trên UI (thêm dấu câu, viết hoa).
     *            KHÔNG ảnh hưởng đến keyword matching — chỉ dùng cho hiển thị.
     * Tham số:
     *   text : chuỗi text thô từ ASR recognizer
     * Trả về: str text đã được format với dấu câu và viết hoa câu
     * Luồng hoạt động:
     *   1. Chuẩn hóa khoảng trắng thừa.
     *   2. Xóa khoảng trắng trước dấu câu.
     *   3. Viết hoa đầu câu qua _capitalize_sentences().
     *   4. Thêm dấu câu cuối qua _guess_sentence_ending() nếu chưa có.
     */
    """
    if not text:
        return ""
    formatted = re.sub(r"\s+", " ", text).strip()
    formatted = re.sub(r"\s+([,.!?;:])", r"\1", formatted)
    if not formatted:
        return ""
    formatted = _capitalize_sentences(formatted)
    if formatted[-1] not in SENTENCE_ENDINGS:
        formatted += _guess_sentence_ending(formatted)
    return formatted


def _capitalize_sentences(text: str) -> str:
    """
    /**
     * Chức năng: Viết hoa chữ cái đầu mỗi câu trong chuỗi text.
     * Tham số:
     *   text : chuỗi text cần viết hoa đầu câu
     * Trả về: str đã viết hoa đầu câu
     * Luồng hoạt động:
     *   1. Duyệt từng ký tự, theo dõi trạng thái capitalize_next.
     *   2. Viết hoa ký tự alpha đầu tiên sau dấu câu kết thúc hoặc đầu chuỗi.
     */
    """
    chars = list(text)
    capitalize_next = True
    for index, char in enumerate(chars):
        if char.isspace():
            continue
        if capitalize_next and char.isalpha():
            chars[index] = char.upper()
            capitalize_next = False
            continue
        if char in SENTENCE_ENDINGS:
            capitalize_next = True
        else:
            capitalize_next = False
    return "".join(chars)


def _guess_sentence_ending(text: str) -> str:
    """
    /**
     * Chức năng: Đoán dấu câu cuối phù hợp dựa trên nội dung text.
     * Tham số:
     *   text : chuỗi text cần thêm dấu câu cuối
     * Trả về: "!" nếu từ khẩn cấp, "?" nếu từ hỏi, "." ngược lại
     * Luồng hoạt động:
     *   1. Lowercase text và kiểm tra URGENT_HINTS → "!".
     *   2. Kiểm tra QUESTION_HINTS → "?".
     *   3. Mặc định trả ".".
     */
    """
    lowered = text.lower()
    if any(hint in lowered for hint in URGENT_HINTS):
        return "!"
    if any(hint in lowered for hint in QUESTION_HINTS):
        return "?"
    return "."


# ─────────────────────────────────────────────────────────
# MIC STREAM
# ─────────────────────────────────────────────────────────

class MicStream:
    """
    Đọc mic liên tục → phát hiện câu nói bằng Silero VAD (hoặc Energy VAD nếu thiếu)
    → đẩy audio numpy float32 vào result_queue khi câu kết thúc.
    """

    def __init__(self, result_queue: queue.Queue):
        """
        /**
         * Chức năng: Khởi tạo MicStream với queue nhận kết quả audio và chọn
         *            chunk size theo VAD backend (Silero hoặc Energy).
         * Tham số:
         *   result_queue : Queue nhận mảng audio numpy khi phát hiện xong một câu nói
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lưu result_queue và khởi tạo _raw_queue, flags, thread, stream.
         *   2. Chọn chunk_size = SILERO_CHUNK (512) nếu có Silero, ngược lại Energy chunk.
         *   3. Tính _max_chunks theo MAX_BUFFER_S để cắt câu quá dài.
         */
        """
        self.result_queue = result_queue
        self._raw_queue   = queue.Queue()
        self._running     = False
        self._thread      = None
        self._sd_stream   = None

        if _SILERO_AVAILABLE:
            self._chunk_size = SILERO_CHUNK
        else:
            self._chunk_size = int(SAMPLE_RATE * ENERGY_CHUNK_MS / 1000)

        self._max_chunks = int(MAX_BUFFER_S * SAMPLE_RATE / self._chunk_size)

    def _sd_callback(self, indata, frames, time_info, status):
        """
        /**
         * Chức năng: Callback của sounddevice InputStream — đẩy chunk audio vào _raw_queue.
         * Tham số:
         *   indata    : mảng audio 2D từ mic [frames, channels]
         *   frames    : số sample trong indata
         *   time_info : thông tin thời gian sounddevice
         *   status    : cờ lỗi sounddevice (nếu có)
         * Trả về: None
         * Luồng hoạt động:
         *   1. Log status nếu có lỗi.
         *   2. Lấy kênh 0 (mono) và đẩy vào _raw_queue.
         */
        """
        if status:
            print(f"[MIC] Warning: {status}")
        self._raw_queue.put(indata[:, 0].copy())

    def _process_silero(self):
        """
        /**
         * Chức năng: Vòng lặp xử lý VAD bằng Silero — phát hiện start/end của câu nói
         *            và flush vào result_queue khi câu kết thúc.
         * Tham số: Không
         * Trả về: None (loop vô tận đến khi _running = False)
         * Luồng hoạt động:
         *   1. Load Silero VAD model và tạo VADIterator.
         *   2. Dùng pre_buffer (deque) để bắt đầu câu sớm hơn.
         *   3. Khi VAD trả "start": bắt đầu tích lũy speech_buffer từ pre_buffer.
         *   4. Khi VAD trả "end": flush speech_buffer, reset.
         *   5. Khi quá _max_chunks: tự flush (cắt câu dài).
         */
        """
        print("[VAD] Đang tải Silero VAD model ...")
        model = load_silero_vad()
        vad   = VADIterator(
            model,
            threshold=SILERO_THRESHOLD,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=SILERO_MIN_SILENCE_MS,
            speech_pad_ms=SILERO_PAD_MS,
        )
        print("[VAD] Silero VAD sẵn sàng.")

        pre_buffer    = deque(maxlen=SILERO_PRE_CHUNKS)
        speech_buffer = []
        in_speech     = False

        while self._running:
            try:
                chunk = self._raw_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            chunk_tensor = torch.from_numpy(chunk)
            result       = vad(chunk_tensor, return_seconds=False)

            if result and "start" in result:
                in_speech     = True
                speech_buffer = list(pre_buffer) + [chunk]
            elif result and "end" in result:
                if in_speech:
                    speech_buffer.append(chunk)
                    self._flush(speech_buffer)
                    speech_buffer = []
                    in_speech     = False
                    vad.reset_states()
            else:
                if in_speech:
                    speech_buffer.append(chunk)
                    if len(speech_buffer) >= self._max_chunks:
                        self._flush(speech_buffer)
                        speech_buffer = []
                        in_speech     = False
                        vad.reset_states()
                else:
                    pre_buffer.append(chunk)

    def _process_energy(self):
        """
        /**
         * Chức năng: Vòng lặp xử lý VAD bằng ngưỡng năng lượng (Energy VAD fallback).
         * Tham số: Không
         * Trả về: None (loop vô tận đến khi _running = False)
         * Luồng hoạt động:
         *   1. Đọc chunk từ _raw_queue.
         *   2. Nếu có giọng nói: tích lũy vào buffer, reset silence_count.
         *   3. Nếu im lặng: tăng silence_count; flush khi đủ SILENCE_MS.
         *   4. Tự flush khi buffer quá _max_chunks.
         */
        """
        silence_chunks = int(SILENCE_MS / ENERGY_CHUNK_MS)
        buffer         = []
        silence_count  = 0
        in_speech      = False

        while self._running:
            try:
                chunk = self._raw_queue.get(timeout=0.5)
            except queue.Empty:
                if in_speech and buffer:
                    silence_count += 1
                    if silence_count >= silence_chunks:
                        self._flush(buffer)
                        buffer = []; silence_count = 0; in_speech = False
                continue

            if _is_speech(chunk):
                silence_count = 0; in_speech = True; buffer.append(chunk)
                if len(buffer) >= self._max_chunks:
                    self._flush(buffer); buffer = []; in_speech = False
            else:
                if in_speech:
                    silence_count += 1; buffer.append(chunk)
                    if silence_count >= silence_chunks:
                        self._flush(buffer)
                        buffer = []; silence_count = 0; in_speech = False

    def _flush(self, buffer: list):
        """
        /**
         * Chức năng: Ghép danh sách chunk audio thành mảng numpy và đẩy vào result_queue.
         * Tham số:
         *   buffer : danh sách các chunk numpy float32
         * Trả về: None
         * Luồng hoạt động:
         *   1. Thoát ngay nếu buffer rỗng.
         *   2. Concatenate tất cả chunk thành mảng float32.
         *   3. Đưa vào result_queue để thread ASR xử lý.
         */
        """
        if not buffer:
            return
        audio = np.concatenate(buffer).astype(np.float32)
        self.result_queue.put(audio)

    def start(self):
        """
        /**
         * Chức năng: Khởi động MicStream — mở sounddevice InputStream và bắt đầu
         *            thread xử lý VAD (Silero hoặc Energy).
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đặt _running = True; chọn target thread theo VAD backend.
         *   2. Khởi động daemon thread xử lý VAD.
         *   3. Mở sd.InputStream với device/samplerate/blocksize đã cấu hình.
         *   4. Gọi stream.start() để bắt đầu nhận dữ liệu mic.
         */
        """
        self._running = True

        if _SILERO_AVAILABLE:
            target   = self._process_silero
            name     = "mic-silero"
        else:
            target   = self._process_energy
            name     = "mic-energy"

        self._thread = threading.Thread(target=target, daemon=True, name=name)
        self._thread.start()

        device_name = sd.query_devices(MIC_DEVICE)["name"] if MIC_DEVICE is not None else "System Default"
        print(f"[MIC] Sử dụng device {MIC_DEVICE}: {device_name}")

        self._sd_stream = sd.InputStream(
            device=MIC_DEVICE,
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=self._chunk_size,
            callback=self._sd_callback,
        )
        self._sd_stream.start()

        if _SILERO_AVAILABLE:
            print(f"[MIC] Đang lắng nghe (Silero VAD | threshold={SILERO_THRESHOLD} | silence={SILERO_MIN_SILENCE_MS}ms)")
        else:
            print(f"[MIC] Đang lắng nghe (Energy VAD | threshold={ENERGY_THRESHOLD} | silence={SILENCE_MS}ms)")

    def stop(self):
        """
        /**
         * Chức năng: Dừng MicStream — đóng sounddevice stream và join VAD thread.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Đặt _running = False để VAD thread thoát vòng lặp.
         *   2. Dừng và đóng _sd_stream.
         *   3. Join _thread với timeout 2s.
         */
        """
        self._running = False
        if self._sd_stream:
            self._sd_stream.stop()
            self._sd_stream.close()
        if self._thread:
            self._thread.join(timeout=2)
        print("[MIC] Đã dừng.")


# ─────────────────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    vad_label = "Silero VAD" if _SILERO_AVAILABLE else "Energy VAD (fallback)"
    print("=" * 60)
    print(f"  ASR Test — gipformer-65M-rnnt + {vad_label}")
    print("  Chỉ tiếng Việt | Nói vào mic | Ctrl+C để dừng")
    print("=" * 60)

    get_recognizer()

    audio_queue: queue.Queue[np.ndarray] = queue.Queue()
    mic = MicStream(result_queue=audio_queue)
    mic.start()

    try:
        while True:
            try:
                audio_chunk = audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            text = transcribe_chunk(audio_chunk)
            if text:
                print(f"\n  >>> {text}\n")

    except KeyboardInterrupt:
        mic.stop()
        print("\n[ASR] Test kết thúc.")
