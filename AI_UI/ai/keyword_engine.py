import os
import re
import time
import logging
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from services.uart_service import uart_service
from services.database_service import database_service


# ─────────────────────────────────────────────────────────
# COOLDOWN (giây) — ngăn spam SMS lúc hoảng loạn
# P0: 5 phút — tính mạng, gia đình đã nhận được 1 SMS
# P1: 2 phút — nguy hiểm
# P2: 1 phút — cần hỗ trợ
# P3: 2 phút — nhu cầu thông thường
# ─────────────────────────────────────────────────────────

COOLDOWN_BY_PRIORITY = {
    0: 30,   # demo: 30s (sản phẩm thực tế: 300s)
    1: 20,   # demo: 20s (sản phẩm thực tế: 120s)
    2: 15,   # demo: 15s (sản phẩm thực tế: 60s)
    3: 20,   # demo: 20s (sản phẩm thực tế: 120s)
}

# Từ phủ định tiếng Việt — xuất hiện trước keyword → không cảnh báo
NEGATION_WORDS = frozenset({
    "không", "chưa", "chẳng", "chả", "đâu", "đừng"
})
_NEG_WINDOW = 5  # kiểm tra tối đa N từ trước keyword

# "nhưng" giữa từ phủ định và keyword → phủ định bị đảo ngược
# "không sao nhưng đau lắm" → "không" bị "nhưng" huỷ → vẫn alert
_REVERSAL_WORDS = frozenset({"nhưng"})

# Từ điều kiện / giả định trước keyword → không cảnh báo
# "nếu": luôn suppress — "nếu đau thì gọi tôi", "nếu khó thở thì kêu"
# "lỡ" + "thì" theo sau keyword: suppress — "lỡ ngã thì bấm nút"
# "lỡ" không có "thì": không suppress — "lỡ ngã rồi" (đã xảy ra thật)

# Từ cuối câu dạng hỏi: "có đau không?", "bị ngã chưa?", "đau hả?", "ngã hở?"
_QUESTION_PARTICLES = frozenset({"không", "chưa", "hả", "hở", "thế nhỉ"})

# Từ lịch sự / đệm cuối câu (stripped trước khi kiểm tra question)
_SENTENCE_FILLERS = frozenset({"ạ", "vậy", "nha", "nhé", "đó", "hả", "hở", "à", "nhỉ"})

# Từ dismissal sau "nhưng" → "đau quá nhưng không sao" → suppress (chỉ P2/P3)
_DISMISSAL_AFTER = frozenset({
    "không", "chẳng", "chả",   # phủ định sau nhưng
    "ổn", "khỏe", "tốt",       # trạng thái tốt
    "bình", "đỡ", "được",      # phục hồi
    "hết", "khỏi",             # đã hết triệu chứng
})

# Từ cường độ — xuất hiện ngay sau root word → fallback match khi không khớp exact keyword
# "đau kinh", "mệt ghê", "sốt nặng", "nhức quá" v.v.
_INTENSIFIER_WORDS = frozenset({"lắm", "quá", "dữ", "kinh", "ghê", "nặng"})

# Fallback P2: root + intensifier khi main keyword loop không trả kết quả
_INTENSIFIER_FALLBACK = [
    {
        "priority": 2, "category": "dau_nguoi_benh",
        "roots": {"đau", "nhức", "buốt", "ê", "rát"},
        "sms_text": "[P2]Đau {time}: {text}",
    },
    {
        "priority": 2, "category": "met_moi",
        "roots": {"mệt", "yếu", "kiệt", "đuối", "lả"},
        "sms_text": "[P2]Mệt {time}: {text}",
    },
    {
        "priority": 2, "category": "sot",
        "roots": {"sốt"},
        "sms_text": "[P2]Sốt {time}: {text}",
    },
    {
        "priority": 2, "category": "chong_mat",
        "roots": {"chóng", "choáng"},
        "sms_text": "[P2]Chóng mặt {time}: {text}",
    },
]

# Dấu hiệu quá khứ xa → suppress P3 (nhu cầu thông thường từ hôm qua không còn liên quan)
# P0/P1/P2 KHÔNG bị suppress — an toàn là trên hết
_PAST_DISTANT_PHRASES = [
    "hôm qua", "hôm kia", "tuần trước", "tháng trước",
    "hôm bữa", "lần trước", "ngày hôm qua",
]
# Nếu cùng câu có từ hiện tại → không suppress ("hôm qua đói, bây giờ vẫn đói")
_PRESENT_OVERRIDE_PHRASES = ["bây giờ", "hiện tại", "đang ", "vẫn còn", "vừa "]

# ─────────────────────────────────────────────────────────
# TWO-STRIKE RULE — nhóm "gọi người thân" (P3)
#
# Lần gọi đầu chỉ ghi nhận, CHƯA gửi SMS.
# Lần gọi thứ hai trong _CALL_CONFIRM_S giây → gửi SMS.
# Bypass ngay (không cần lần 2) nếu trong cùng thời điểm
# xuất hiện keyword P0/P1/P2 (tình huống thực sự khẩn cấp).
# ─────────────────────────────────────────────────────────

_CALL_CATEGORIES = frozenset({
    "goi_me", "goi_ba", "goi_ong", "goi_ba_noi", "nguoi_cham_soc",
    "goi_con", "goi_hang_xom",
})
_CALL_CONFIRM_S = 10   # demo: 10s (sản phẩm thực tế: 45s)

# ─────────────────────────────────────────────────────────
# SMS PENDING — lưu packet đã gửi để retry khi FAILED
# key: packet_id → {"packet": {...}, "retry_count": int}
# ─────────────────────────────────────────────────────────

_sms_pending: dict = {}

# ─────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────

_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "keyword_engine.log"
)

log = logging.getLogger("keyword_engine")

if not log.handlers:
    log.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    from logging.handlers import RotatingFileHandler
    _fh = RotatingFileHandler(_LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    _fh.setFormatter(_fmt)
    log.addHandler(_sh)
    log.addHandler(_fh)


# ─────────────────────────────────────────────────────────
# KEYWORD DATABASE
#
# Prefix SMS rút gọn: "[Px]Code HH:MM: {text}"
# Tối đa 20 ký tự prefix → còn ~50 ký tự cho nội dung speech
# trong giới hạn 70 ký tự UCS2 của A7680C.
#
# Quy tắc khớp:
#   - Text ASR được normalize (lowercase, NFC, bỏ ký tự thừa)
#   - Keyword khớp nếu là SUBSTRING của text đã normalize
#   - short_keywords: dành cho trẻ nhỏ / câu < 3 từ
# ─────────────────────────────────────────────────────────

KEYWORD_DB = [

    # ══════════════════════════════════════════════════════
    # PRIORITY 0 — Nguy hiểm tính mạng
    # ══════════════════════════════════════════════════════

    {
        "priority": 0, "category": "kho_tho",
        "keywords": ["khó thở","thở không được","thở không ra","không thở được",
                     "ngộp thở","ngạt thở","thở khó","thở mệt","thở gấp","không thở nổi",
                     # Người già / phương ngữ
                     "thở không ra hơi","thở hổn hển","hơi thở yếu","thở dốc",
                     "không thở ra hơi","ngộp quá","thở nặng lắm",
                     # Bổ sung: triệu chứng hen / COPD người già
                     "thở khò khè","thở rít","thở có tiếng","ngực bóp","ngực tức khó thở",
                     "khò khè không thở được","thở rít quá"],
        # "hổn hển" thêm vào short_keywords: người già suy hô hấp hay chỉ nói được 1 từ.
        "short_keywords": ["ngộp","ngạt","khó thở","thở gấp","thở khó","hổn hển","thở mệt"],
        "sms_text": "[P0]Khó thở {time}: {text}"
    },
    {
        "priority": 0, "category": "dau_tim",
        "keywords": ["đau ngực","tức ngực","đau tim","tim đau","ngực đau",
                     "khó chịu trong ngực","đánh trống ngực","tim đập mạnh","tim đập nhanh","nặng ngực",
                     "ngực thắt lại","nghẹt ngực","toát mồ hôi lạnh","đau lan ra tay","tim nhảy loạn",
                     "đau lan lên cổ","ngực bóp chặt","tim đau quá",
                     # Người già thường mô tả:
                     "tim loạn nhịp","tim không đều nhịp","hồi hộp trong ngực",
                     "đau nhói trong ngực","tim đập loạn","tim hồi hộp quá"],
        "short_keywords": [],
        "sms_text": "[P0]Đau tim {time}: {text}"
    },
    {
        "priority": 0, "category": "dot_quy",
        "keywords": ["không dậy","không tỉnh","không mở mắt","không nói được","nói không ra",
                     "miệng méo","tê nửa người","yếu một bên","muốn xỉu","bất tỉnh",
                     "nói ngọng bất ngờ","tê tay đột ngột","đột ngột không thấy",
                     "mặt tê một bên","mất thăng bằng đột ngột","đầu đau dữ dội đột ngột",
                     "chân tay yếu đột ngột",
                     # Cách mô tả đơn giản hơn của người già / trẻ báo:
                     "miệng bị méo","tê liệt một bên","tay chân không cử động được",
                     "nói không ra lời","mặt méo rồi",
                     # Bổ sung: triệu chứng điển hình đột quỵ
                     "nói líu lưỡi","nói không rõ","lưỡi cứng không nói được",
                     "méo miệng đột ngột","mặt xệ một bên","tay không nhấc lên được",
                     "đột ngột không nói được","đột ngột méo miệng"],
        # short_keywords: trẻ thường báo ngắn gọn khi thấy người thân đột quỵ.
        "short_keywords": ["xỉu","bất tỉnh","miệng méo","tê người"],
        "sms_text": "[P0]Đột quỵ {time}: {text}"
    },
    {
        "priority": 0, "category": "chay_no",
        "keywords": ["cháy","có cháy","bốc cháy","có lửa","có khói","khói nhiều","cháy nhà","lửa lớn",
                     "khói um","khói mù","cháy rồi","lửa bùng lên"],
        "short_keywords": ["cháy","lửa","khói"],
        "sms_text": "[P0]Cháy {time}: {text}"
    },
    {
        "priority": 0, "category": "keu_cuu",
        "keywords": ["cứu tôi","cứu với","giúp tôi với","cứu con","cứu cháu",
                     "cứu ông","cứu bà","làm ơn cứu",
                     # Cách gọi thêm của người già / trẻ:
                     "ai cứu với","có ai không","ơi cứu với","ai giúp với",
                     "cứu ông với","cứu bà với","hàng xóm ơi cứu",
                     "gọi cấp cứu","gọi 115","cần gọi 115"],
        # "giúp" ĐÃ XÓA khỏi short_keywords — quá phổ biến, false positive rất cao
        # "cứu" giữ lại: đủ đặc thù để trigger P0 ngay cả khi nói 1 từ
        "short_keywords": ["cứu"],
        "sms_text": "[P0]Cứu cấp {time}: {text}"
    },
    {
        "priority": 0, "category": "tre_bao_bat_thuong",
        "keywords": ["ông không dậy","bà không dậy","ông không nói","bà không nói",
                     "ông không thở","bà không thở","gọi không dậy","không trả lời",
                     # Trẻ thường báo thêm các dạng:
                     "ông ngã rồi","bà ngã rồi","ông xỉu rồi","bà xỉu rồi",
                     "ông không tỉnh","bà không tỉnh","ông ngã không dậy","bà ngã không dậy",
                     "ông bất tỉnh","bà bất tỉnh"],
        "short_keywords": [],
        "sms_text": "[P0]Cần cứu {time}: {text}"
    },
    {
        "priority": 0, "category": "co_giat",
        "keywords": ["co giật","giật liên tục","run toàn thân","sùi bọt mép","động kinh",
                     "người giật","cơ thể giật","giật không ngừng",
                     # Bổ sung: cách trẻ/người thân mô tả co giật
                     "mắt trợn ngược","người cứng đơ","người cứng lại","mắt đảo",
                     "toàn thân cứng","co cứng người","giật tay chân"],
        "short_keywords": [],
        "sms_text": "[P0]Co giật {time}: {text}"
    },
    {
        "priority": 0, "category": "nguy_kich",
        "keywords": ["sắp chết","không ổn rồi","không chịu nổi","không còn thở",
                     "không cử động","không phản ứng",
                     "nguy kịch rồi","không ổn nữa rồi","không chịu được nữa"],
        "short_keywords": [],
        "sms_text": "[P0]Nguy cấp {time}: {text}"
    },
    {
        "priority": 0, "category": "dien_giat",
        "keywords": ["bị điện giật","điện giật","bị giật điện","điện chích",
                     "chạm phải điện","điện đánh tôi","bị điện đánh",
                     "chạm điện rồi","bị điện rồi"],
        "short_keywords": [],
        "sms_text": "[P0]Điện giật {time}: {text}"
    },
    {
        "priority": 0, "category": "nghen_tho",
        # "hóc"/"nghẹn" là short_keywords: trẻ nhỏ đang hóc thường chỉ kịp nói 1 từ.
        "keywords": ["bị nghẹn","hóc xương","hóc thức ăn","mắc trong cổ họng",
                     "nuốt không được","cổ bị nghẹn","hóc rồi",
                     "có cái gì trong cổ","đang bị nghẹn","cổ họng bị mắc",
                     "nuốt bị mắc","có gì mắc cổ","hóc xương cá"],
        "short_keywords": ["nghẹn","hóc"],
        "sms_text": "[P0]Nghẹn {time}: {text}"
    },

    # ══════════════════════════════════════════════════════
    # PRIORITY 1 — Khẩn cấp
    # ══════════════════════════════════════════════════════

    {
        "priority": 1, "category": "nga_te",
        "keywords": ["té rồi","ngã rồi","té xuống","ngã xuống","bị té","bị ngã",
                     "té khỏi giường","ngã khỏi giường","té trong nhà tắm",
                     "té cầu thang","rớt xuống","rớt khỏi giường",
                     "bị trượt","bị vấp ngã","trượt nhà tắm","trượt cầu thang",
                     "đứng lên không được","ngã xuống đất rồi","trượt té rồi",
                     # Người già hay dùng thêm:
                     "té nhào","nhào xuống","quỵ xuống","té quỵ",
                     "nằm không dậy được","nằm không dậy nổi",
                     "ngã không dậy được","không đứng dậy được rồi",
                     "trượt ngã rồi","ngã trong phòng tắm"],
        # "nhào","quỵ" thêm vào short_keywords cho trẻ báo ngắn gọn.
        "short_keywords": ["té","ngã","nhào","quỵ"],
        "sms_text": "[P1]Ngã té {time}: {text}"
    },
    {
        "priority": 1, "category": "chay_mau",
        "keywords": ["chảy máu","máu nhiều","đang chảy máu","tay chảy máu","chân chảy máu",
                     "đầu chảy máu","bị đứt tay","bị đứt chân","máu không ngừng",
                     "nôn ra máu","ói ra máu","đi cầu ra máu","ỉa ra máu","đại tiện ra máu",
                     "máu chảy không cầm","đứt tay rồi","đứt chân rồi"],
        "short_keywords": ["máu","chảy máu"],
        "sms_text": "[P1]Chảy máu {time}: {text}"
    },
    {
        "priority": 1, "category": "bi_can",
        "keywords": ["bị cắn","con chó cắn","con mèo cắn","rắn cắn","côn trùng cắn","ong đốt","bị đốt",
                     "chó cắn rồi","rắn cắn rồi","bị ong đốt"],
        "short_keywords": ["cắn","đốt"],
        "sms_text": "[P1]Bị cắn {time}: {text}"
    },
    {
        "priority": 1, "category": "bong",
        # "nóng quá"/"nước nóng" standalone đã XÓA — gây false positive
        # khi người già xin nước nóng ("cho tôi nước nóng").
        "keywords": ["bị bỏng","phỏng tay","phỏng chân","bỏng rồi",
                     "bỏng điện","dầu sôi bắn","lửa đốt tay",
                     "bỏng nước nóng","nước sôi đổ","dầu sôi văng",
                     "phỏng rồi","bỏng nặng lắm","bỏng tay rồi"],
        "short_keywords": ["bỏng","phỏng"],
        "sms_text": "[P1]Bỏng {time}: {text}"
    },
    {
        "priority": 1, "category": "gay_xuong",
        "keywords": ["gãy tay","gãy chân","gãy xương","bị gãy tay","bị gãy chân",
                     "xương bị gãy","tay bị gãy","chân bị gãy","gãy rồi",
                     "xương gãy rồi","tay gãy rồi","chân gãy rồi"],
        "short_keywords": [],
        "sms_text": "[P1]Gãy xương {time}: {text}"
    },
    {
        "priority": 1, "category": "di_ung_nang",
        "keywords": ["nổi mẩn đỏ","ngứa khắp người","sưng mặt","mặt sưng phù",
                     "môi sưng lên","dị ứng rồi","toàn thân nổi mẩn","khắp người ngứa",
                     "nổi mề đay","mắt sưng lên",
                     "người nổi đỏ","ngứa dữ lắm","sưng phù rồi"],
        "short_keywords": [],
        "sms_text": "[P1]Dị ứng {time}: {text}"
    },
    {
        "priority": 1, "category": "ngo_doc",
        "keywords": ["ngộ độc","uống nhầm thuốc","uống nhầm hóa chất","ăn phải độc",
                     "ngộ độc thức ăn","ăn bị độc","uống nhầm rồi","ăn nhầm phải cái gì",
                     "bị trúng độc","ngộ độc rồi",
                     "bị ngộ độc","ăn vào bị sao","uống vào bị sao"],
        "short_keywords": [],
        "sms_text": "[P1]Ngộ độc {time}: {text}"
    },
    {
        "priority": 1, "category": "bi_xam_hai",
        # Dành cho trẻ em bị đánh, bắt nạt, nguy hiểm từ người lạ.
        "keywords": ["bị đánh","người ta đánh con","người ta đánh cháu",
                     "bị bắt nạt","bạn đánh con","bạn đánh cháu",
                     "bị kéo đi","người lạ kéo con","người lạ bắt con",
                     "bị bắt đi","con bị bắt","cháu bị bắt",
                     "có người đánh con","có người kéo","bị nhốt trong phòng",
                     "không ra được rồi","nhốt con lại","bị người lạ","người lạ theo con"],
        "short_keywords": [],
        "sms_text": "[P1]Nguy hiểm {time}: {text}"
    },
    {
        "priority": 1, "category": "tu_tu",
        # Sức khoẻ tâm thần — quan trọng với người già sống một mình.
        # Negation check tự động xử lý: "không muốn chết" → suppressed.
        "keywords": ["muốn chết","không muốn sống nữa","chán sống rồi",
                     "tự tử","muốn tự tử","sống không nổi nữa",
                     "không muốn sống","chán đời rồi",
                     "sống làm gì nữa","không thiết sống nữa","muốn kết thúc"],
        "short_keywords": [],
        "sms_text": "[P1]Tự tử {time}: {text}"
    },

    # ══════════════════════════════════════════════════════
    # PRIORITY 2 — Cần hỗ trợ
    # ══════════════════════════════════════════════════════

    {
        "priority": 2, "category": "dau_nguoi_benh",
        "keywords": ["đau lắm","đau quá","đau dữ","đau đầu","đau bụng","đau lưng",
                     "đau chân","đau tay","nhức đầu","nhức người",
                     # Người già và trẻ hay dùng thêm:
                     "đau ruột","đau bụng dữ","nhức đầu dữ","đau người quá",
                     "toàn thân đau","đau nhức khắp người","đau không chịu nổi"],
        "short_keywords": [],
        "sms_text": "[P2]Đau {time}: {text}"
    },
    {
        "priority": 2, "category": "met_moi",
        "keywords": ["mệt quá","mệt lắm","mệt rồi","yếu quá","không khỏe",
                     "khó chịu quá","không có sức","đuối quá",
                     "kiệt sức rồi","mệt không đứng được","người mệt lắm",
                     "mệt xỉu","không còn sức nữa","mệt không dậy được"],
        "short_keywords": [],
        "sms_text": "[P2]Mệt {time}: {text}"
    },
    {
        "priority": 2, "category": "uong_thuoc",
        # "chưa..." đặt TRƯỚC để không bị negation filter chặn.
        "keywords": ["đến giờ uống thuốc",
                     "chưa uống thuốc","chưa lấy thuốc",
                     "uống thuốc","quên uống thuốc","lấy thuốc giúp","cho uống thuốc",
                     # Người già thường nói:
                     "thuốc đâu rồi","thuốc hết rồi","cần uống thuốc",
                     "quên uống thuốc rồi","chưa lấy thuốc uống"],
        "short_keywords": [],
        "sms_text": "[P2]Thuốc {time}: {text}"
    },
    {
        "priority": 2, "category": "sot",
        # "nóng quá" đã XÓA — conflict với lanh_nong (P3): "nóng quá bật quạt" trigger sai P2
        # "người nóng" XÓA — quá ngắn, dùng "người nóng hầm"/"nóng người quá" thay thế
        "keywords": ["sốt","sốt rồi","sốt cao","rét run","lạnh run",
                     "người nóng hầm","sốt không hạ","nóng người quá","sốt mấy ngày rồi",
                     "nóng sốt","thân nhiệt cao","sốt li bì","sốt cao quá"],
        "short_keywords": ["sốt"],
        "sms_text": "[P2]Sốt {time}: {text}"
    },
    {
        "priority": 2, "category": "chong_mat",
        "keywords": ["chóng mặt","hoa mắt","quay cuồng","đứng không vững","choáng quá","choáng váng",
                     "đứng lên bị tối mắt","ngồi dậy bị hoa mắt","đứng dậy chóng mặt",
                     "đầu quay cuồng","mắt tối sầm",
                     # Thêm mô tả phổ biến người già:
                     "loạng choạng","đầu quay vòng","không vững nữa",
                     "đứng không vững nữa","chân loạng choạng","đầu quay tròn"],
        "short_keywords": [],
        "sms_text": "[P2]Chóng mặt {time}: {text}"
    },
    {
        "priority": 2, "category": "buon_non",
        "keywords": ["buồn nôn","muốn ói","ói quá","nôn rồi","khó chịu trong bụng","đau bụng muốn ói",
                     # Phương ngữ miền Nam:
                     "buồn ói","ói mửa","mửa rồi","đang ói","mửa hoài",
                     "ói không ngừng","ói dữ lắm","buồn ói quá"],
        "short_keywords": [],
        "sms_text": "[P2]Buồn nôn {time}: {text}"
    },
    {
        "priority": 2, "category": "ho",
        "keywords": ["ho nhiều","ho quá","ho không ngừng","ho không dứt","ho suốt","ho mãi",
                     "ho có đờm","khó chịu ở cổ họng","cổ họng đau",
                     "ho dữ lắm","ho nặng lắm","ho từng cơn",
                     "ho ra máu","ho ra đờm nhiều","ho rát cổ"],
        "short_keywords": [],
        "sms_text": "[P2]Ho {time}: {text}"
    },
    {
        "priority": 2, "category": "dau_khop",
        "keywords": ["đau khớp","đau gối","đau đầu gối","đau háng","đau lưng dưới",
                     "cứng khớp","khớp đau","khớp cứng lại","đau khi đi","đau khi đứng",
                     "sưng khớp","khớp sưng","nhức khớp","khớp nhức",
                     # Người già viêm khớp, thấp khớp:
                     "đau thấp khớp","khớp sưng đỏ","đi đứng đau lắm","nhức xương"],
        "short_keywords": [],
        "sms_text": "[P2]Đau khớp {time}: {text}"
    },
    {
        "priority": 2, "category": "huyet_ap",
        # Huyết áp cao là bệnh rất phổ biến ở người già.
        "keywords": ["huyết áp cao","tăng huyết áp","đo huyết áp cao",
                     "huyết áp tăng","huyết áp không ổn","huyết áp lên cao",
                     "đầu căng dữ lắm","tức đầu quá","đầu căng như muốn vỡ",
                     "thuốc huyết áp hết rồi","quên uống thuốc huyết áp",
                     "huyết áp thấp","huyết áp tụt","người tụt huyết áp"],
        "short_keywords": [],
        "sms_text": "[P2]Huyết áp {time}: {text}"
    },
    {
        "priority": 2, "category": "mat_ngu",
        "keywords": ["không ngủ được","mất ngủ","khó ngủ","thức cả đêm","ngủ không được",
                     "trằn trọc không ngủ","thức trắng đêm","ngủ không yên"],
        "short_keywords": [],
        "sms_text": "[P2]Mất ngủ {time}: {text}"
    },
    {
        "priority": 2, "category": "lac_duong",
        # Người già (sa sút trí tuệ) và trẻ em đi lạc.
        "keywords": ["bị lạc","lạc đường","không biết đường về","quên đường về",
                     "con lạc rồi","cháu lạc rồi","không nhớ đường về",
                     "đi lạc rồi","không biết mình ở đâu","đang lạc đường",
                     "lạc mất rồi","quên mất đường về","không tìm được đường về",
                     "không biết ở đâu rồi","lạc không biết chỗ"],
        "short_keywords": [],
        "sms_text": "[P2]Lạc đường {time}: {text}"
    },
    {
        "priority": 2, "category": "tre_bao_nguoi_benh",
        "keywords": ["ông kêu đau","bà kêu đau","ông kêu mệt","bà kêu mệt",
                     "ông không khỏe","bà không khỏe","ông khóc","bà khóc","ông run","bà run",
                     # Trẻ thêm nhiều cách báo:
                     "ông đau bụng","bà đau bụng","ông mệt lắm","bà mệt lắm",
                     "ông nói đau","bà nói đau","ông nằm không dậy","bà nằm không dậy"],
        "short_keywords": [],
        "sms_text": "[P2]Trẻ báo {time}: {text}"
    },
    {
        "priority": 2, "category": "can_ho_tro",
        "keywords": ["giúp con với","giúp cháu với","con cần giúp","cháu cần giúp",
                     "con không làm được","cháu không làm được","giúp ông với","giúp bà với",
                     # Người già tự xin trợ giúp:
                     "tôi cần giúp","cần người giúp","giúp tôi với","không làm được rồi",
                     "già rồi không làm được","cần người đỡ","đỡ tôi với"],
        "short_keywords": [],
        "sms_text": "[P2]Hỗ trợ {time}: {text}"
    },
    {
        "priority": 2, "category": "tam_ly",
        "keywords": ["con sợ","sợ quá","lo quá","buồn quá","khóc rồi","con đang khóc","cháu đang khóc",
                     # Trẻ em và người già thêm:
                     "sợ lắm","hoảng sợ","đang sợ","lo sợ quá","hoảng loạn",
                     "một mình sợ lắm","sợ quá không ngủ được","cháu đang khóc sợ"],
        "short_keywords": [],
        "sms_text": "[P2]Tâm lý {time}: {text}"
    },

    # ══════════════════════════════════════════════════════
    # PRIORITY 3 — Nhu cầu thông thường
    # ══════════════════════════════════════════════════════

    {
        "priority": 3, "category": "khat_nuoc",
        "keywords": ["khát nước","con khát","cho con uống nước","uống nước",
                     "muốn uống nước","cho cháu uống nước",
                     # Người già hay nói:
                     "khô miệng quá","miệng khô lắm","cho tôi uống nước"],
        "short_keywords": [],
        "sms_text": "[P3]Khát {time}: {text}"
    },
    {
        "priority": 3, "category": "doi_bung",
        "keywords": ["đói bụng","con đói","muốn ăn","cho con ăn","cho cháu ăn","con muốn ăn",
                     # Phương ngữ và người già:
                     "bụng đói","cháu đói","muốn ăn cơm","cho tôi ăn","đói rồi","đói quá"],
        "short_keywords": [],
        "sms_text": "[P3]Đói {time}: {text}"
    },
    {
        "priority": 3, "category": "di_ve_sinh",
        "keywords": ["đi vệ sinh","muốn đi vệ sinh","muốn đi tiểu","đi tiểu","đi cầu","cần đi vệ sinh",
                     # Người già thường dùng:
                     "muốn đi toilet","cần đi cầu","muốn đi tiêu","đi ị"],
        "short_keywords": [],
        "sms_text": "[P3]Vệ sinh {time}: {text}"
    },
    {
        "priority": 3, "category": "tro_minh",
        "keywords": ["trở mình","trở người","đổi tư thế","nằm mỏi quá","giúp con trở mình",
                     "nằm một chỗ mỏi quá","trở tư thế giúp","giúp ông trở mình","giúp bà trở mình"],
        "short_keywords": [],
        "sms_text": "[P3]Trở mình {time}: {text}"
    },
    {
        "priority": 3, "category": "muon_ngu",
        "keywords": ["buồn ngủ","muốn ngủ","con muốn ngủ","cháu muốn ngủ","đi ngủ thôi",
                     "ngủ rồi","muốn đi ngủ","buồn ngủ rồi"],
        "short_keywords": [],
        "sms_text": "[P3]Ngủ {time}: {text}"
    },
    {
        "priority": 3, "category": "lanh_nong",
        "keywords": ["lạnh quá","nóng quá","lạnh lắm","nóng bức quá",
                     "đắp mền giúp","đắp mền cho","đắp chăn giúp","đắp chăn cho",
                     "bật quạt giúp","bật quạt cho","tắt quạt giúp","tắt quạt cho",
                     "bật máy lạnh giúp","bật máy lạnh cho","tắt máy lạnh giúp","tắt máy lạnh cho",
                     "mở cửa sổ cho mát","mở cửa sổ giúp"],
        "short_keywords": [],
        "sms_text": "[P3]Nhiệt độ {time}: {text}"
    },
    {
        "priority": 3, "category": "tro_chuyen",
        "keywords": ["nói chuyện với con","con buồn","cháu buồn","ở với con",
                     "ở với cháu","trò chuyện với con",
                     # Người già hay cảm thấy cô đơn:
                     "muốn có người bên cạnh","một mình buồn quá","ở một mình sợ",
                     "cô đơn quá","không có ai bên cạnh"],
        "short_keywords": [],
        "sms_text": "[P3]Nói chuyện {time}: {text}"
    },
    {
        "priority": 3, "category": "xem_tivi",
        "keywords": ["muốn xem tivi","cho xem tivi","xem hoạt hình","xem phim",
                     "mở tivi giúp","mở tivi cho","bật tivi giúp","bật tivi cho",
                     "mở ti vi giúp","mở ti vi cho","bật ti vi giúp","bật ti vi cho"],
        "short_keywords": [],
        "sms_text": "[P3]Ti vi {time}: {text}"
    },
    {
        "priority": 3, "category": "muon_choi",
        "keywords": ["muốn chơi","chơi với con","chơi với cháu","con muốn chơi","cháu muốn chơi",
                     "chơi với ông","chơi với bà","ra ngoài chơi"],
        "short_keywords": [],
        "sms_text": "[P3]Chơi {time}: {text}"
    },
    {
        "priority": 3, "category": "goi_me",
        "keywords": ["mẹ ơi","mẹ đâu","gọi mẹ","con cần mẹ",
                     # Phương ngữ miền Nam: "má" thay cho "mẹ"
                     "má ơi","gọi má","con cần má","má đâu","má ơi con cần má"],
        "short_keywords": [],
        "sms_text": "[P3]Gọi mẹ {time}: {text}"
    },
    {
        "priority": 3, "category": "goi_ba",
        "keywords": ["ba ơi","bố ơi","gọi ba","gọi bố","con cần ba",
                     "ba đâu","bố đâu","con cần bố"],
        "short_keywords": [],
        "sms_text": "[P3]Gọi ba {time}: {text}"
    },
    {
        "priority": 3, "category": "goi_ong",
        "keywords": ["ông ơi","gọi ông","con cần ông",
                     "ông đâu","cháu cần ông"],
        "short_keywords": [],
        "sms_text": "[P3]Gọi ông {time}: {text}"
    },
    {
        "priority": 3, "category": "goi_ba_noi",
        "keywords": ["bà ơi","gọi bà","con cần bà",
                     "bà đâu","cháu cần bà"],
        "short_keywords": [],
        "sms_text": "[P3]Gọi bà {time}: {text}"
    },
    {
        "priority": 3, "category": "goi_con",
        # Người già gọi con cái về nhà hoặc cần con giúp đỡ.
        "keywords": ["gọi con về","con về đây","gọi con trai","gọi con gái",
                     "con ơi","gọi con giúp","con đâu rồi","cần con về",
                     "con ơi về đây","con trai ơi", "con gái ơi"],
        "short_keywords": [],
        "sms_text": "[P3]Gọi con {time}: {text}"
    },
    {
        "priority": 3, "category": "goi_hang_xom",
        # Khi người già ở một mình cần hàng xóm hỗ trợ.
        "keywords": ["hàng xóm ơi","nhờ hàng xóm","gọi hàng xóm giúp",
                     "hàng xóm giúp với","nhờ hàng xóm giúp","có hàng xóm không"],
        "short_keywords": [],
        "sms_text": "[P3]Hàng xóm {time}: {text}"
    },
    {
        "priority": 3, "category": "nguoi_cham_soc",
        "keywords": ["cô ơi","chú ơi","người chăm sóc","gọi cô","gọi chú",
                     "cô đâu rồi","chú đâu rồi","cần cô giúp","cần chú giúp"],
        "short_keywords": [],
        "sms_text": "[P3]Gọi chăm sóc {time}: {text}"
    },
]

# Pre-sort một lần ở module level — tránh sorted() O(n log n) mỗi lần evaluate()
KEYWORD_DB_SORTED = sorted(KEYWORD_DB, key=lambda e: e["priority"])


# ─────────────────────────────────────────────────────────
# TEXT NORMALIZATION
# ─────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    /**
     * Chức năng: Chuẩn hóa text ASR về dạng so khớp — lowercase, NFC Unicode,
     *            xóa ký tự đặc biệt, gộp khoảng trắng.
     * Tham số:
     *   text : chuỗi text thô cần chuẩn hóa
     * Trả về: str đã normalize
     * Luồng hoạt động:
     *   1. NFC normalize + lowercase.
     *   2. Xóa tất cả ký tự không phải chữ/số/dấu tiếng Việt/khoảng trắng.
     *   3. Gộp khoảng trắng thừa và strip.
     */
    """
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(
        r"[^\w\sàáâãèéêìíòóôõùúýăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ]",
        " ", text
    )
    return re.sub(r"\s+", " ", text).strip()


def _match_kw_words(text_words: list, kw_words: list) -> bool:
    """
    /**
     * Chức năng: Kiểm tra chuỗi từ của keyword có xuất hiện LIÊN TIẾP trong
     *            text_words theo ranh giới từ nguyên vẹn.
     * Tham số:
     *   text_words : danh sách từ của text đã normalize
     *   kw_words   : danh sách từ của keyword đã normalize
     * Trả về: True nếu khớp liên tiếp, False nếu không
     * Luồng hoạt động:
     *   1. Thoát ngay nếu kw dài hơn text hoặc rỗng.
     *   2. Dùng sliding window so sánh từng vị trí trong text_words.
     */
    """
    kn = len(kw_words)
    tn = len(text_words)
    if kn == 0 or kn > tn:
        return False
    for i in range(tn - kn + 1):
        if text_words[i : i + kn] == kw_words:
            return True
    return False


def _has_negation_before(text_words: list, kw_words: list) -> bool:
    """
    /**
     * Chức năng: Kiểm tra có từ phủ định hiệu lực trong _NEG_WINDOW từ trước keyword.
     *            Xử lý các ngoại lệ: keyword bắt đầu bằng phủ định, "ở đâu", "nhưng".
     * Tham số:
     *   text_words : danh sách từ của text
     *   kw_words   : danh sách từ của keyword
     * Trả về: True nếu có phủ định hiệu lực, False ngược lại
     * Luồng hoạt động:
     *   1. Bỏ qua nếu keyword bắt đầu bằng từ phủ định (bản thân là tình trạng cần alert).
     *   2. Tìm vị trí keyword trong text, lấy context _NEG_WINDOW từ trước.
     *   3. Kiểm tra từng từ phủ định trong context với các ngoại lệ "ở đâu", "nhưng".
     */
    """
    if not kw_words or kw_words[0] in NEGATION_WORDS:
        return False

    kn = len(kw_words)
    tn = len(text_words)
    for i in range(tn - kn + 1):
        if text_words[i : i + kn] == kw_words:
            context = text_words[max(0, i - _NEG_WINDOW) : i]
            for j, word in enumerate(context):
                if word not in NEGATION_WORDS:
                    continue
                # Ngoại lệ 2: "ở đâu" = hỏi vị trí
                if word == "đâu" and j > 0 and context[j - 1] == "ở":
                    continue
                # Ngoại lệ 3: có "nhưng" nằm giữa từ phủ định và keyword
                # → phủ định của mệnh đề trước bị đảo ngược
                if any(w in _REVERSAL_WORDS for w in context[j + 1:]):
                    continue
                return True
    return False


def _has_conditional_before(text_words: list, kw_words: list, kw_end: int) -> bool:
    """
    /**
     * Chức năng: Kiểm tra keyword nằm trong mệnh đề giả định ("nếu", "lỡ...thì").
     * Tham số:
     *   text_words : danh sách từ của text
     *   kw_words   : danh sách từ của keyword
     *   kw_end     : vị trí kết thúc của keyword trong text_words
     * Trả về: True nếu là câu giả định, False nếu là tình trạng thực
     * Luồng hoạt động:
     *   1. Lấy _NEG_WINDOW từ trước keyword (before).
     *   2. Nếu có "nếu" trong before → suppress.
     *   3. Nếu có "lỡ" trong before → chỉ suppress khi có "thì" sau keyword.
     */
    """
    kw_start = kw_end - len(kw_words)
    before = text_words[max(0, kw_start - _NEG_WINDOW) : kw_start]
    if "nếu" in before:
        return True
    if "lỡ" in before:
        after = text_words[kw_end : kw_end + 4]
        return "thì" in after
    return False


def _find_kw_end(text_words: list, kw_words: list) -> int:
    """
    /**
     * Chức năng: Tìm vị trí kết thúc (exclusive) của lần khớp keyword đầu tiên.
     * Tham số:
     *   text_words : danh sách từ của text
     *   kw_words   : danh sách từ của keyword
     * Trả về: int vị trí kết thúc, hoặc -1 nếu không khớp
     * Luồng hoạt động:
     *   1. Sliding window tìm vị trí khớp đầu tiên.
     *   2. Trả i + len(kw_words) hoặc -1.
     */
    """
    kn = len(kw_words)
    for i in range(len(text_words) - kn + 1):
        if text_words[i : i + kn] == kw_words:
            return i + kn
    return -1


def _is_question_form(text_words: list, kw_end: int) -> bool:
    """
    /**
     * Chức năng: Kiểm tra câu có dạng hỏi thăm (không phải báo tình trạng thật).
     * Tham số:
     *   text_words : danh sách từ của text
     *   kw_end     : vị trí kết thúc keyword
     * Trả về: True nếu là câu hỏi thăm cần suppress, False ngược lại
     * Luồng hoạt động:
     *   1. Kiểm tra từ cuối cùng có trong _QUESTION_PARTICLES.
     *   2. Bỏ qua từ đệm cuối câu (_SENTENCE_FILLERS) rồi kiểm tra lại.
     */
    """
    end = len(text_words)
    if end > kw_end and text_words[end - 1] in _QUESTION_PARTICLES:
        return True
    while end > kw_end and text_words[end - 1] in _SENTENCE_FILLERS:
        end -= 1
    if end <= kw_end:
        return False
    return text_words[end - 1] in _QUESTION_PARTICLES


def _has_reversal_after(text_words: list, kw_end: int) -> bool:
    """
    /**
     * Chức năng: Kiểm tra sau keyword có "nhưng" + từ dismissal — người dùng
     *            tự đánh giá không nghiêm trọng (chỉ áp dụng P2/P3).
     * Tham số:
     *   text_words : danh sách từ của text
     *   kw_end     : vị trí kết thúc keyword
     * Trả về: True nếu cần suppress P2/P3, False ngược lại
     * Luồng hoạt động:
     *   1. Lấy suffix sau keyword.
     *   2. Tìm "nhưng" trong suffix; kiểm tra 3 từ sau "nhưng" có trong _DISMISSAL_AFTER.
     */
    """
    suffix = text_words[kw_end:]
    try:
        nhung_pos = suffix.index("nhưng")
    except ValueError:
        return False
    after = suffix[nhung_pos + 1 : nhung_pos + 4]
    return any(w in _DISMISSAL_AFTER for w in after)


def _find_root_intensifier_match(
    text_words: list, roots: set, intensifiers: set, window: int = 2
) -> tuple:
    """
    /**
     * Chức năng: Tìm root word + intensifier xuất hiện trong vòng 'window' từ sau
     *            (fallback match khi không có keyword chính xác trong DB).
     * Tham số:
     *   text_words  : danh sách từ của text
     *   roots       : tập root words (đã normalize)
     *   intensifiers: tập từ cường độ
     *   window      : số từ tối đa sau root để tìm intensifier
     * Trả về: tuple (root, end_pos) hoặc (None, -1) nếu không tìm thấy
     * Luồng hoạt động:
     *   1. Duyệt text_words tìm word trong roots.
     *   2. Tìm intensifier trong window từ tiếp theo.
     *   3. Trả (root, j+1) khi tìm thấy.
     */
    """
    n = len(text_words)
    for i, w in enumerate(text_words):
        if w not in roots:
            continue
        for j in range(i + 1, min(i + 1 + window, n)):
            if text_words[j] in intensifiers:
                return w, j + 1
    return None, -1


def _is_past_distant(norm_text: str) -> bool:
    """
    /**
     * Chức năng: Kiểm tra utterance chỉ nói về sự kiện quá khứ xa mà không có
     *            từ hiện tại đi kèm — dùng để suppress P3.
     * Tham số:
     *   norm_text : chuỗi text đã normalize
     * Trả về: True nếu chỉ nói về quá khứ xa (không có từ hiện tại), False ngược lại
     * Luồng hoạt động:
     *   1. Kiểm tra có từ quá khứ xa (_PAST_DISTANT_PHRASES).
     *   2. Nếu có: kiểm tra thêm từ hiện tại (_PRESENT_OVERRIDE_PHRASES) → không suppress.
     */
    """
    if not any(p in norm_text for p in _PAST_DISTANT_PHRASES):
        return False
    return not any(p in norm_text for p in _PRESENT_OVERRIDE_PHRASES)


# ─────────────────────────────────────────────────────────
# MATCH RESULT
# ─────────────────────────────────────────────────────────

@dataclass
class MatchResult:
    matched:  bool
    priority: int = 0
    category: str = ""
    keyword:  str = ""
    sms_text: str = ""


def evaluate(text: str) -> MatchResult:
    """
    /**
     * Chức năng: Đánh giá text ASR có khớp keyword nào trong KEYWORD_DB không —
     *            với đầy đủ các bộ lọc ngữ nghĩa và fallback intensifier.
     * Tham số:
     *   text : chuỗi text ASR thô cần đánh giá
     * Trả về: MatchResult với matched=True và thông tin nếu khớp, matched=False nếu không
     * Luồng hoạt động:
     *   1. Normalize text; phân loại câu ngắn (< 3 từ) để dùng short_keywords.
     *   2. Duyệt KEYWORD_DB_SORTED (pre-sorted theo priority).
     *   3. Với mỗi keyword: kiểm tra word-boundary match → negation → conditional → question → reversal.
     *   4. Trả MatchResult ngay khi tìm được keyword đầu tiên vượt qua tất cả bộ lọc.
     *   5. Fallback: root + intensifier match cho P2 nếu không khớp keyword chính.
     *   6. Trả MatchResult(matched=False) nếu không có gì khớp.
     */
    """
    norm       = _normalize(text)
    text_words = norm.split()
    is_short   = len(text_words) < 3
    now_str    = datetime.now().strftime("%H:%M")

    for entry in KEYWORD_DB_SORTED:
        # P3 only: bỏ qua nhu cầu thông thường nếu câu chỉ nói về quá khứ xa
        if entry["priority"] == 3 and _is_past_distant(norm):
            continue

        short_kws = entry.get("short_keywords", [])
        if is_short:
            keyword_list = short_kws if short_kws else entry["keywords"]
        else:
            keyword_list = entry["keywords"] + short_kws

        for kw in keyword_list:
            kw_words = _normalize(kw).split()
            if not _match_kw_words(text_words, kw_words):
                continue
            if _has_negation_before(text_words, kw_words):
                log.debug(f"[NEGATION] Bỏ qua '{kw}' — bị phủ định trong: '{text}'")
                continue
            kw_end = _find_kw_end(text_words, kw_words)
            if _has_conditional_before(text_words, kw_words, kw_end):
                log.debug(f"[CONDITIONAL] Bỏ qua '{kw}' — câu giả định: '{text}'")
                continue
            if _is_question_form(text_words, kw_end):
                log.debug(f"[QUESTION] Bỏ qua '{kw}' — câu hỏi thăm: '{text}'")
                continue
            if entry["priority"] >= 2 and _has_reversal_after(text_words, kw_end):
                log.debug(f"[REVERSAL] Bỏ qua '{kw}' — 'nhưng' đảo ngữ P{entry['priority']}: '{text}'")
                continue
            return MatchResult(
                matched=True,
                priority=entry["priority"],
                category=entry["category"],
                keyword=kw,
                sms_text=entry["sms_text"].format(text=text, time=now_str),
            )

    # ── Fallback: root + intensifier ─────────────────────────────────────
    # Bắt các cụm không có trong DB nhưng rõ ràng chỉ mức độ nghiêm trọng:
    # "đau kinh", "mệt ghê", "sốt nặng", "nhức quá" v.v.
    for info in _INTENSIFIER_FALLBACK:
        roots_norm = {_normalize(r) for r in info["roots"]}
        root, end_pos = _find_root_intensifier_match(
            text_words, roots_norm, _INTENSIFIER_WORDS
        )
        if root is None:
            continue
        if _has_negation_before(text_words, [root]):
            log.debug(f"[INTENSIFIER] Bỏ qua root '{root}' — bị phủ định: '{text}'")
            continue
        if _has_conditional_before(text_words, [root], end_pos):
            log.debug(f"[INTENSIFIER] Bỏ qua root '{root}' — câu giả định: '{text}'")
            continue
        if _is_question_form(text_words, end_pos):
            log.debug(f"[INTENSIFIER] Bỏ qua root '{root}' — câu hỏi: '{text}'")
            continue
        log.debug(
            f"[INTENSIFIER] KHỚP root='{root}' → {info['category']} "
            f"P{info['priority']}: '{text}'"
        )
        return MatchResult(
            matched=True,
            priority=info["priority"],
            category=info["category"],
            keyword=f"{root}+intensifier",
            sms_text=info["sms_text"].format(text=text, time=now_str),
        )

    return MatchResult(matched=False)


# ─────────────────────────────────────────────────────────
# KEYWORD ENGINE
# ─────────────────────────────────────────────────────────

class KeywordEngine:

    def __init__(self):
        """
        /**
         * Chức năng: Khởi tạo KeywordEngine với bảng cooldown và two-strike tracking.
         * Tham số: Không
         * Trả về: None
         * Luồng hoạt động:
         *   1. Khởi tạo _last_sent (category → timestamp) để theo dõi cooldown.
         *   2. Đặt _paused = False.
         *   3. Khởi tạo _pending_calls (category → timestamp lần gọi đầu) cho two-strike rule.
         */
        """
        self._last_sent: dict[str, float] = {}
        self._paused = False
        self._pending_calls: dict[str, float] = {}  # category → thời điểm lần gọi đầu

    def pause(self):
        """
        /**
         * Chức năng: Tạm dừng engine — không xử lý text trong chế độ manual SMS.
         * Tham số: Không
         * Trả về: None
         */
        """
        self._paused = True

    def resume(self):
        """
        /**
         * Chức năng: Tiếp tục engine sau khi manual SMS kết thúc.
         * Tham số: Không
         * Trả về: None
         */
        """
        self._paused = False

    def process(self, text: str, match=None) -> bool:
        """
        /**
         * Chức năng: Xử lý text ASR — kiểm tra cooldown, two-strike rule rồi
         *            gửi SMS async nếu đủ điều kiện.
         * Tham số:
         *   text  : chuỗi text ASR cần xử lý
         *   match : MatchResult từ evaluate() nếu đã có, None thì tự gọi evaluate()
         * Trả về: True nếu SMS được kích hoạt gửi, False nếu bị chặn
         * Luồng hoạt động:
         *   1. Bỏ qua nếu engine bị pause hoặc text rỗng.
         *   2. Gọi evaluate() nếu match=None; thoát nếu không khớp.
         *   3. Kiểm tra cooldown theo category; thoát nếu còn cooldown.
         *   4. Two-strike rule: nhóm gọi người thân P3 cần lần gọi thứ 2.
         *   5. Cập nhật _last_sent và gửi SMS qua thread async.
         */
        """
        if self._paused or not text or not text.strip():
            return False

        result = match if match is not None else evaluate(text)
        if not result.matched:
            log.info(f"[ENGINE] Bỏ qua ({len(text.split())} từ): '{text}'")
            return False

        log.info(
            f"[ENGINE] KHỚP priority={result.priority} "
            f"category={result.category} keyword='{result.keyword}'"
        )

        cooldown = COOLDOWN_BY_PRIORITY.get(result.priority, 60)
        now = time.time()
        if now - self._last_sent.get(result.category, 0) < cooldown:
            remaining = cooldown - (now - self._last_sent[result.category])
            log.info(f"[ENGINE] Cooldown còn {remaining:.0f}s cho '{result.category}'")
            return False

        # ── Two-strike rule: nhóm "gọi người thân" P3 ───────────────────
        # Bypass nếu P0/P1/P2 (khẩn cấp thực sự — không cần gọi lần 2).
        if result.category in _CALL_CATEGORIES and result.priority >= 3:
            first = self._pending_calls.get(result.category, 0)
            if now - first > _CALL_CONFIRM_S:
                # Lần gọi đầu hoặc hết hạn — ghi nhận, chưa gửi
                self._pending_calls[result.category] = now
                log.info(
                    f"[ENGINE] [{result.category}] Lần gọi 1 — "
                    f"chờ xác nhận trong {_CALL_CONFIRM_S}s"
                )
                return False
            else:
                # Lần gọi thứ hai trong window → cho gửi
                del self._pending_calls[result.category]
                log.info(
                    f"[ENGINE] [{result.category}] Lần gọi 2 "
                    f"(+{now - first:.0f}s) — gửi SMS"
                )

        self._last_sent[result.category] = now
        threading.Thread(
            target=self._send_sms_async,
            args=(result.priority, result.category, result.sms_text),
            daemon=True
        ).start()
        return True

    def _send_sms_async(self, priority: int, category: str, message: str):
        """
        /**
         * Chức năng: Gửi SMS đến các số điện thoại theo priority trong background thread.
         * Tham số:
         *   priority : mức ưu tiên (0-3) để lấy danh sách số điện thoại tương ứng
         *   category : danh mục cảnh báo (dùng để log)
         *   message  : nội dung SMS đã format
         * Trả về: None
         * Luồng hoạt động:
         *   1. Lấy danh sách phones theo priority từ database_service.
         *   2. Với mỗi phone: tạo SEND_SMS packet, lưu vào _sms_pending, gửi qua uart_service.
         *   3. Delay 3s giữa các SMS để ESP32 xử lý tuần tự.
         */
        """
        try:
            phones = database_service.get_phones_by_priority(priority)
            if not phones:
                log.warning("[ENGINE] Không tìm thấy số điện thoại")
                return
            for phone in phones:
                pkt = {
                    "type": "COMMAND",
                    "command": "SEND_SMS",
                    "packet_id": f"SMS_{int(time.time()*1000)}",
                    "source": "AI_UI",
                    "target": "ESP32",
                    "timestamp": int(time.time()),
                    "payload": {
                        "phone": phone,
                        "priority": priority,
                        "category": category,
                        "message": message,
                    },
                }
                _sms_pending[pkt["packet_id"]] = {"packet": pkt, "retry_count": 0}
                uart_service.send_packet(pkt)
                log.info(f"[ENGINE] SEND_SMS P{priority} | {category} | {phone}")
                time.sleep(3)
        except Exception as e:
            log.error(f"[ENGINE] Lỗi gửi SMS: {e}")

    def close(self):
        """
        /**
         * Chức năng: Dọn dẹp tài nguyên khi đóng engine (hiện không có tài nguyên cần giải phóng).
         * Tham số: Không
         * Trả về: None
         */
        """
        pass
