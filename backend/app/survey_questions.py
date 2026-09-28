"""The clinician questionnaire: mostly about what the model produced.

An earlier draft led with the ten items of the System Usability Scale, which
buys a score comparable to a published mean of 68. That comparability was not
worth ten of sixteen questions here: the thesis is about grading quality, the
clinicians are giving up their time once, and what a committee will ask about
is whether the grades were right -- not whether the buttons were easy to find.
So usability keeps two questions and the model gets fourteen, and the price is
that the usability number stands alone with nothing to compare it against.

Four of the clinical items are marked ``core`` and required; the rest are
``detail`` and may be skipped. Someone who read two studies can still say
whether the grades matched their reading, while a question about foraminal
stenosis specifically deserves a blank rather than a guess.
"""

from typing import Literal

Kind = Literal["usability", "core", "detail"]
REQUIRED_KINDS = ("usability", "core")


class Question:
    __slots__ = ("id", "text", "kind", "group")

    def __init__(self, id: int, text: str, kind: Kind, group: str) -> None:
        self.id = id
        self.text = text
        self.kind = kind
        self.group = group

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "group": self.group,
            "required": self.kind in REQUIRED_KINDS,
        }


SEG = "Phân vùng"
GRADE = "Điểm chẩn đoán"
ERRORS = "Khi AI sai"
SHOW = "Cách trình bày kết quả"
USE = "Sử dụng trong công việc"
UX = "Mức dễ dùng"

QUESTIONS: list[Question] = [
    # Every item names an aspect to be rated from very poor to very good, and
    # every one is oriented so that 5 is the good end. A statement to agree
    # with ("the AI rarely misses severe lesions") reads oddly against a
    # quality scale, and one worded negatively would silently invert its mean.

    # --- What the segmentation drew -------------------------------------
    Question(1, "Độ khớp của vùng AI tô với ranh giới đốt sống và đĩa đệm trên phim", "core", SEG),
    Question(2, "Độ dễ nhìn của màu và đường viền vùng tô (không che mất chi tiết cần đọc)", "detail", SEG),
    Question(3, "Mức vùng tô giúp tôi xác định nhanh tầng cần xem", "detail", SEG),

    # --- Whether the grades are right ------------------------------------
    Question(4, "Độ khớp của điểm chẩn đoán AI với đánh giá của tôi", "core", GRADE),
    # Split by condition on purpose: the model is measurably weaker on
    # foraminal stenosis than on the others, so a single average would hide
    # exactly the disagreement worth reporting.
    Question(5, "Độ chính xác của mức hẹp ống sống (canal stenosis)", "detail", GRADE),
    Question(6, "Độ chính xác của mức hẹp lỗ liên hợp (foraminal stenosis)", "detail", GRADE),
    Question(7, "Độ chính xác của phân độ thoái hoá đĩa đệm (Pfirrmann)", "detail", GRADE),

    # --- Whether the presentation does any work ---------------------------
    Question(8, "Mức bảng kết quả theo tầng giúp tôi nắm cả đoạn cột sống trong một lần nhìn", "detail", SHOW),
    Question(9, "Mức tính năng bấm vào dòng để nhảy tới lát cắt giúp tôi kiểm chứng nhanh", "detail", SHOW),
    Question(10, "Mức ảnh lát cắt AI đánh dấu giúp tôi hiểu AI căn cứ vào đâu", "detail", SHOW),

    # --- How it fails, which accuracy alone cannot say --------------------
    Question(11, "Mức an toàn khi AI sai (sai lệch nhỏ, dễ nhận ra)", "core", ERRORS),
    Question(12, "Khả năng phát hiện tổn thương nặng, không bỏ sót", "detail", ERRORS),
    Question(13, "Khả năng tránh báo động giả ở ca bình thường", "detail", ERRORS),

    # --- Whether it survives contact with a working day -------------------
    Question(14, "Mức thuận tiện khi sửa mask và sửa điểm", "detail", USE),
    Question(15, "Độ tin cậy của kết quả AI khi tham khảo lúc đọc phim", "detail", USE),
    Question(16, "Mức công cụ rút ngắn thời gian đọc một ca so với đọc thủ công", "detail", USE),
    Question(17, "Mức phù hợp để đưa công cụ vào công việc thường ngày", "core", USE),

    Question(18, "Mức phần mềm đáp ứng nhu cầu công việc của tôi", "usability", UX),
    Question(19, "Mức dễ sử dụng của phần mềm", "usability", UX),
]

CLINICAL_IDS = [q.id for q in QUESTIONS if q.kind in ("core", "detail")]
USABILITY_IDS = [q.id for q in QUESTIONS if q.kind == "usability"]
REQUIRED_IDS = [q.id for q in QUESTIONS if q.kind in REQUIRED_KINDS]
GROUPS = list(dict.fromkeys(q.group for q in QUESTIONS))

SCALE_MIN, SCALE_MAX = 1, 5
# A quality scale rather than agree/disagree: clinicians rate an aspect
# directly, which reads more naturally than weighing a statement, and needs no
# reversed items to decode.
SCALE_LABELS = [
    "Rất kém",
    "Kém",
    "Trung bình",
    "Tốt",
    "Rất tốt",
]


def mean_of(answers: dict[int, int], ids: list[int]) -> float | None:
    """Mean over the ids actually answered, or None when none were.

    Averaging only what was answered is what makes skipping safe: a blank
    lowers nothing, so a clinician who did not look at foraminal crops is not
    quietly penalising the model for it.
    """
    values = [answers[i] for i in ids if i in answers]
    return round(sum(values) / len(values), 2) if values else None
