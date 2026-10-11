# -*- coding: utf-8 -*-
"""
eval_accuracy.py
─────────────────────────────────────────────────────────────────────
Đánh giá độ chính xác của Keyword Engine trên tập câu thực tế.

Xuất ra:
  - Bảng Precision / Recall / F1 theo từng mức ưu tiên (P0-P3)
  - Bảng Precision / Recall / F1 tổng thể (có alert / không alert)
  - Danh sách False Positive và False Negative chi tiết

Dùng cho chương "Thực Nghiệm & Đánh Giá" của báo cáo tốt nghiệp.
─────────────────────────────────────────────────────────────────────
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from ai.keyword_engine import evaluate

# ═════════════════════════════════════════════════════════════════════
# TẬP DỮ LIỆU ĐÁNH GIÁ
#
# Mỗi entry: (text, expected_priority_or_None, expected_category_or_"")
#   priority = None  → hệ thống KHÔNG nên cảnh báo (no alert)
#   priority = 0-3   → hệ thống PHẢI cảnh báo đúng mức
#
# Nguồn: câu thực tế từ người già, người chăm sóc, trẻ nhỏ báo tin.
# Đa dạng: nói đầy đủ, nói ngắn, nói lộn xộn, câu hỏi thăm, phủ định.
# ═════════════════════════════════════════════════════════════════════

EVAL_SET = [

    # ──────────────────────────────────────────────────────────────
    # NHÓM P0 — Nguy hiểm tính mạng (should alert P0)
    # ──────────────────────────────────────────────────────────────

    # Khó thở
    ("khó thở",                               0, "kho_tho"),
    ("thở không được",                        0, "kho_tho"),
    ("thở gấp quá",                           0, "kho_tho"),
    ("ngộp thở rồi",                          0, "kho_tho"),
    ("bà đang thở không ra",                  0, "kho_tho"),
    ("ông ngộp thở",                          0, "kho_tho"),

    # Đau tim / nhồi máu cơ tim
    ("đau ngực lắm",                          0, "dau_tim"),
    ("tức ngực quá",                          0, "dau_tim"),
    ("ngực thắt lại",                         0, "dau_tim"),
    ("tim đập mạnh lắm",                      0, "dau_tim"),
    ("toát mồ hôi lạnh",                      0, "dau_tim"),
    ("đau lan ra tay trái",                   0, "dau_tim"),

    # Đột quỵ
    ("miệng méo rồi",                         0, "dot_quy"),
    ("tê nửa người",                          0, "dot_quy"),
    ("bà không dậy được",                     0, "dot_quy"),
    ("nói không ra tiếng",                    0, "dot_quy"),
    ("tê tay đột ngột",                       0, "dot_quy"),
    ("mặt tê một bên",                        0, "dot_quy"),

    # Cứu cấp / kêu cứu
    ("cứu",                                   0, "keu_cuu"),
    ("cứu tôi với",                           0, "keu_cuu"),
    ("giúp tôi với",                          0, "keu_cuu"),

    # Cháy
    ("cháy nhà rồi",                          0, "chay_no"),
    ("có khói nhiều lắm",                     0, "chay_no"),
    ("có lửa",                                0, "chay_no"),

    # Điện giật
    ("bị điện giật rồi",                      0, "dien_giat"),
    ("chạm phải điện rồi",                    0, "dien_giat"),

    # Hóc nghẹn
    ("bị nghẹn rồi",                          0, "nghen_tho"),
    ("hóc xương cá",                          0, "nghen_tho"),
    ("nghẹn",                                 0, "nghen_tho"),
    ("hóc",                                   0, "nghen_tho"),

    # Co giật
    ("co giật rồi",                           0, "co_giat"),
    ("giật liên tục",                         0, "co_giat"),

    # ──────────────────────────────────────────────────────────────
    # NHÓM P1 — Khẩn cấp (should alert P1)
    # ──────────────────────────────────────────────────────────────

    # Ngã té
    ("bị ngã rồi",                            1, "nga_te"),
    ("té xuống đất rồi",                      1, "nga_te"),
    ("ngã khỏi giường",                       1, "nga_te"),
    ("trượt nhà tắm rồi",                     1, "nga_te"),
    ("đứng lên không được",                   1, "nga_te"),

    # Chảy máu
    ("chảy máu nhiều lắm",                    1, "chay_mau"),
    ("tay đang chảy máu",                     1, "chay_mau"),
    ("đầu chảy máu",                          1, "chay_mau"),
    ("ói ra máu rồi",                         1, "chay_mau"),

    # Bỏng
    ("bị bỏng tay rồi",                       1, "bong"),
    ("dầu sôi bắn vào tay",                   1, "bong"),
    ("bỏng điện",                             1, "bong"),

    # Gãy xương
    ("gãy tay rồi",                           1, "gay_xuong"),
    ("gãy chân rồi",                          1, "gay_xuong"),
    ("ngã gãy xương",                         1, "gay_xuong"),

    # Dị ứng nặng
    ("nổi mẩn đỏ khắp người",                1, "di_ung_nang"),
    ("mặt sưng phù lên",                      1, "di_ung_nang"),

    # Ngộ độc
    ("ngộ độc thức ăn rồi",                   1, "ngo_doc"),
    ("uống nhầm thuốc rồi",                   1, "ngo_doc"),

    # Sức khoẻ tâm thần
    ("muốn tự tử",                            1, "tu_tu"),
    ("chán sống rồi",                         1, "tu_tu"),
    ("không muốn sống nữa",                   1, "tu_tu"),

    # ──────────────────────────────────────────────────────────────
    # NHÓM P2 — Cần hỗ trợ (should alert P2)
    # ──────────────────────────────────────────────────────────────

    ("đau đầu quá",                           2, "dau_nguoi_benh"),
    ("đau bụng lắm",                          2, "dau_nguoi_benh"),
    ("nhức đầu dữ",                           2, "dau_nguoi_benh"),
    ("đau lưng quá",                          2, "dau_nguoi_benh"),
    ("đau kinh",                              2, "dau_nguoi_benh"),   # intensifier fallback
    ("nhức kinh",                             2, "dau_nguoi_benh"),   # intensifier fallback
    ("mệt quá",                               2, "met_moi"),
    ("mệt lắm không đứng được",              2, "met_moi"),
    ("mệt ghê",                               2, "met_moi"),          # intensifier fallback
    ("sốt rồi",                               2, "sot"),
    ("người nóng hầm",                         2, "sot"),
    ("chóng mặt",                             2, "chong_mat"),
    ("hoa mắt",                               2, "chong_mat"),
    ("đứng lên bị tối mắt",                  2, "chong_mat"),
    ("buồn nôn quá",                          2, "buon_non"),
    ("mất ngủ hoài",                          2, "mat_ngu"),
    ("không ngủ được",                        2, "mat_ngu"),
    ("ho nhiều quá",                          2, "ho"),
    ("ho không ngừng",                        2, "ho"),
    ("ho từng cơn",                           2, "ho"),
    ("đau khớp",                              2, "dau_khop"),
    ("đau gối lắm",                           2, "dau_khop"),
    ("khớp cứng lại",                         2, "dau_khop"),

    # ──────────────────────────────────────────────────────────────
    # NHÓM P3 — Nhu cầu thông thường (should alert P3)
    # ──────────────────────────────────────────────────────────────

    ("con đói",                               3, "doi_bung"),
    ("muốn ăn cơm",                           3, "doi_bung"),
    ("khát nước",                             3, "khat_nuoc"),
    ("cho con uống nước",                     3, "khat_nuoc"),
    ("muốn đi vệ sinh",                       3, "di_ve_sinh"),
    ("đi tiểu",                               3, "di_ve_sinh"),
    ("lạnh quá",                              3, "lanh_nong"),
    ("nóng quá",                              3, "lanh_nong"),
    ("buồn ngủ",                              3, "muon_ngu"),
    ("muốn ngủ",                              3, "muon_ngu"),
    ("mẹ ơi",                                 3, "goi_me"),
    ("bà ơi",                                 3, "goi_ba_noi"),
    ("ông ơi",                                3, "goi_ong"),
    ("muốn xem tivi",                         3, "xem_tivi"),
    ("bật tivi giúp",                         3, "xem_tivi"),    # "bật tivi" độc lập đã xoá → cần hậu tố

    # Bộ lọc reversal — P0 không bị suppress dù có "nhưng không sao"
    ("khó thở nhưng không sao",               0, "kho_tho"),     # P0 → reversal không áp dụng → vẫn alert

    # "lỡ" đã xảy ra thật — không có "thì" → vẫn alert
    ("lỡ ngã rồi",                            1, "nga_te"),
    ("lỡ bị bỏng rồi",                        1, "bong"),

    # Intensifier fallback — biến thể chưa có trong keyword DB
    ("đau dữ",                                2, "dau_nguoi_benh"),

    # Trường hợp khó — hệ thống nhận diện đúng
    ("đau quá không ngủ được",               2, "dau_nguoi_benh"), # "không" sau intensifier → không bị suppress
    ("đau không chịu nổi",                   0, "nguy_kich"),      # "không chịu nổi" là keyword P0 → hệ thống ưu tiên đúng
    ("ngã xuống nhưng không sao",            1, "nga_te"),         # reversal chỉ P2+ → P1 vẫn alert
    ("mẹ ở đâu con khó thở quá",            0, "kho_tho"),        # "đâu" sau "ở" = hỏi vị trí, không phải phủ định
    ("hôm qua đói quá bây giờ vẫn đói quá", 3, "doi_bung"),       # quá khứ + present override → vẫn alert

    # ──────────────────────────────────────────────────────────────
    # NHÓM KHÔNG CÓ CẢNH BÁO — False positive risk (should NOT alert)
    # ──────────────────────────────────────────────────────────────

    # Phủ định rõ ràng
    ("không khó thở",                         None, ""),
    ("không đau gì cả",                       None, ""),
    ("chân không bị gãy",                     None, ""),
    ("không bị điện giật",                    None, ""),
    ("con không muốn chết",                   None, ""),
    ("không bị ngã",                          None, ""),

    # Câu hỏi thăm
    ("bà có khó thở không",                   None, ""),
    ("bị ngã chưa",                           None, ""),
    ("đau không ạ",                           None, ""),
    ("có chảy máu không",                     None, ""),
    ("muốn chết không",                       None, ""),
    ("khó thở không",                         None, ""),

    # Dismissal — người nói tự đánh giá nhẹ (chỉ P2/P3)
    ("đau đầu nhưng không sao",               None, ""),
    ("mệt nhưng ổn rồi",                      None, ""),

    # Quá khứ xa (P3 suppress)
    ("hôm qua con đói",                       None, ""),
    ("tuần trước con khát",                   None, ""),
    ("hôm kia muốn đi vệ sinh",              None, ""),

    # Câu hỏi thăm — hả/hở (nhận diện mới sau khi thêm vào _QUESTION_PARTICLES)
    ("bị sốt hả",                             None, ""),
    ("đau bụng hở",                           None, ""),
    ("khó thở hả",                            None, ""),

    # Câu giả định — nếu/lỡ...thì (nhận diện mới _has_conditional_before)
    ("nếu khó thở thì kêu tôi",              None, ""),
    ("lỡ ngã thì bấm nút",                   None, ""),
    ("nếu đau thì uống thuốc",               None, ""),
    ("nếu mệt quá thì nói",                  None, ""),    # intensifier path + conditional

    # Dismissal mới — hết/khỏi sau nhưng (P2/P3)
    ("đau đầu nhưng hết rồi",                None, ""),
    ("mệt nhưng khỏi rồi",                   None, ""),

    # Trường hợp khó — hệ thống suppress đúng
    ("bà đang hỏi ông có đau không",        None, ""),    # "không" cuối câu → question detect → suppress

    # Câu bình thường không liên quan
    ("thời tiết hôm nay đẹp quá",            None, ""),
    ("cho tôi nước nóng",                     None, ""),    # xin nước, không phải bỏng
    ("hôm nay ăn cơm ngon",                   None, ""),
    ("con muốn nghe nhạc",                    None, ""),
    ("bà đang xem tivi",                      None, ""),    # đang xem, không phải xin bật
    ("bật tivi lên",                          None, ""),    # caretaker bật TV, không có hậu tố yêu cầu

    # ──────────────────────────────────────────────────────────────
    # GIỚI HẠN ĐÃ BIẾT — Hệ thống xử lý chưa đúng
    # Các case này được đưa vào có chủ đích để minh bạch hóa giới hạn.
    # Output sẽ liệt kê chúng trong FALSE POSITIVE / FALSE NEGATIVE.
    # ──────────────────────────────────────────────────────────────

    # [FP — 3rd person] Người chăm sóc / bác sĩ nhắc triệu chứng, không phải bệnh nhân báo
    # Hệ thống chưa phân biệt được người nói và người được nhắc đến
    ("bác sĩ nói ông bị khó thở",           None, ""),

    # [FN — short text] Người liệt giường chỉ nói được 1 từ đơn
    # short_keywords của dau_nguoi_benh chưa có từ đơn, intensifier fallback cần ít nhất 2 từ
    ("đau",                                  2,    "dau_nguoi_benh"),
]


# ═════════════════════════════════════════════════════════════════════
# CHẠY ĐÁNH GIÁ
# ═════════════════════════════════════════════════════════════════════

def run_evaluation():
    """
    /**
     * Chức năng: Chạy toàn bộ tập EVAL_SET qua Keyword Engine và tính
     *            các chỉ số TP/FP/FN/TN cho từng mức ưu tiên và tổng thể.
     * Tham số: Không
     * Trả về: tuple (per_priority, overall, false_positives, false_negatives, wrong_priority)
     *   - per_priority    : dict {0..3: {tp, fp, fn, tn}}
     *   - overall         : dict {tp, fp, fn, tn} tổng hợp
     *   - false_positives : list các câu bị cảnh báo nhầm
     *   - false_negatives : list các câu bị bỏ sót
     *   - wrong_priority  : list các câu cảnh báo đúng nhưng sai mức
     * Luồng hoạt động:
     *   1. Với mỗi câu test: gọi evaluate() và so sánh với kỳ vọng.
     *   2. Tính TP/FP/FN/TN tổng thể (có/không cảnh báo).
     *   3. Tính TP/FP/FN theo từng mức ưu tiên (P0-P3).
     *   4. Thu thập danh sách lỗi chi tiết.
     *   5. Trả về kết quả để hiển thị.
     */
    """
    # Cấu trúc: per_priority[p] = {tp, fp, fn, tn}
    per_priority = {p: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for p in range(4)}
    overall = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

    false_positives = []
    false_negatives = []
    wrong_priority  = []

    for text, exp_p, exp_cat in EVAL_SET:
        result = evaluate(text)

        should_alert = (exp_p is not None)
        did_alert    = result.matched

        # ── Tổng thể (có alert hay không) ───────────────────────
        if should_alert and did_alert:
            overall["tp"] += 1
        elif should_alert and not did_alert:
            overall["fn"] += 1
            false_negatives.append((text, exp_p, exp_cat, result))
        elif not should_alert and did_alert:
            overall["fp"] += 1
            false_positives.append((text, result))
        else:
            overall["tn"] += 1

        # ── Theo từng mức ưu tiên ────────────────────────────────
        if should_alert:
            p = exp_p
            if did_alert and result.priority == exp_p:
                per_priority[p]["tp"] += 1
            elif did_alert and result.priority != exp_p:
                # Alert nhưng sai priority
                per_priority[p]["fn"] += 1
                wrong_priority.append((text, exp_p, exp_cat, result))
            else:
                per_priority[p]["fn"] += 1
                if (text, exp_p, exp_cat, result) not in false_negatives:
                    false_negatives.append((text, exp_p, exp_cat, result))
        else:
            if did_alert:
                p = result.priority
                per_priority[p]["fp"] += 1

    return per_priority, overall, false_positives, false_negatives, wrong_priority


def prf(tp, fp, fn):
    """
    /**
     * Chức năng: Tính Precision, Recall và F1 Score từ TP, FP, FN.
     * Tham số:
     *   - tp : True Positive count
     *   - fp : False Positive count
     *   - fn : False Negative count
     * Trả về: tuple (precision, recall, f1) — float trong [0.0, 1.0]
     * Luồng hoạt động:
     *   1. Tính precision = tp / (tp + fp), trả về 0 nếu mẫu = 0.
     *   2. Tính recall = tp / (tp + fn), trả về 0 nếu mẫu = 0.
     *   3. Tính f1 = 2*p*r / (p+r), trả về 0 nếu cả hai = 0.
     */
    """
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    return precision, recall, f1


# ═════════════════════════════════════════════════════════════════════
# IN KẾT QUẢ
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    per_p, overall, fps, fns, wrongs = run_evaluation()

    total = len(EVAL_SET)
    alert_cases  = sum(1 for _, p, _ in EVAL_SET if p is not None)
    normal_cases = total - alert_cases

    print()
    print("═" * 70)
    print("  ĐÁNH GIÁ ĐỘ CHÍNH XÁC — KEYWORD ENGINE")
    print(f"  Tổng câu test: {total}  |  Cần cảnh báo: {alert_cases}  |  Bình thường: {normal_cases}")
    print("═" * 70)

    # ── Bảng tổng thể ───────────────────────────────────────────
    print()
    print("[ TỔNG THỂ — Có cảnh báo vs Không cảnh báo ]")
    print(f"  {'':20s}  {'Precision':>10}  {'Recall':>8}  {'F1':>8}  {'TP':>4}  {'FP':>4}  {'FN':>4}  {'TN':>4}")
    print("  " + "-" * 66)
    p, r, f = prf(overall["tp"], overall["fp"], overall["fn"])
    print(f"  {'Tổng hợp':20s}  {p:>9.1%}  {r:>7.1%}  {f:>7.1%}  "
          f"{overall['tp']:>4}  {overall['fp']:>4}  {overall['fn']:>4}  {overall['tn']:>4}")

    # ── Bảng theo mức ưu tiên ───────────────────────────────────
    print()
    print("[ THEO MỨC ƯU TIÊN ]")
    labels = {0: "P0 Nguy hiểm tính mạng", 1: "P1 Khẩn cấp",
              2: "P2 Cần hỗ trợ", 3: "P3 Nhu cầu thường"}
    print(f"  {'':25s}  {'Precision':>10}  {'Recall':>8}  {'F1':>8}  {'TP':>4}  {'FP':>4}  {'FN':>4}")
    print("  " + "-" * 66)
    for lv in range(4):
        s = per_p[lv]
        p, r, f = prf(s["tp"], s["fp"], s["fn"])
        total_for_level = s["tp"] + s["fn"]
        if total_for_level == 0 and s["fp"] == 0:
            continue
        print(f"  {labels[lv]:25s}  {p:>9.1%}  {r:>7.1%}  {f:>7.1%}  "
              f"{s['tp']:>4}  {s['fp']:>4}  {s['fn']:>4}")

    # ── False Positives ─────────────────────────────────────────
    print()
    if fps:
        print(f"[ FALSE POSITIVES — Hệ thống cảnh báo nhầm ({len(fps)} câu) ]")
        for text, res in fps:
            print(f"  ✗ '{text}'  →  P{res.priority}/{res.category} kw='{res.keyword}'")
    else:
        print("[ FALSE POSITIVES: 0 — Không có cảnh báo nhầm ]")

    # ── False Negatives ─────────────────────────────────────────
    print()
    if fns:
        print(f"[ FALSE NEGATIVES — Hệ thống bỏ sót ({len(fns)} câu) ]")
        for text, exp_p, exp_cat, res in fns:
            got = f"P{res.priority}/{res.category}" if res.matched else "không khớp"
            print(f"  ✗ '{text}'  →  mong đợi P{exp_p}/{exp_cat}  |  nhận được: {got}")
    else:
        print("[ FALSE NEGATIVES: 0 — Không có bỏ sót ]")

    # ── Sai mức ưu tiên ─────────────────────────────────────────
    print()
    if wrongs:
        print(f"[ SAI MỨC ƯU TIÊN ({len(wrongs)} câu) ]")
        for text, exp_p, exp_cat, res in wrongs:
            print(f"  ✗ '{text}'  mong P{exp_p}/{exp_cat}  nhận P{res.priority}/{res.category}")
    else:
        print("[ SAI MỨC ƯU TIÊN: 0 ]")

    # ── Kết luận ────────────────────────────────────────────────
    p_ov, r_ov, f_ov = prf(overall["tp"], overall["fp"], overall["fn"])
    accuracy = (overall["tp"] + overall["tn"]) / total

    print()
    print("═" * 70)
    print("  KẾT LUẬN")
    print("═" * 70)
    print(f"  Accuracy  (đúng/tổng)  : {accuracy:>6.1%}  ({overall['tp']+overall['tn']}/{total})")
    print(f"  Precision (chính xác)  : {p_ov:>6.1%}")
    print(f"  Recall    (bao phủ)    : {r_ov:>6.1%}")
    print(f"  F1 Score               : {f_ov:>6.1%}")
    print("═" * 70)
    print()
