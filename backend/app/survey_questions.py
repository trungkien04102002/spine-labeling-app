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
    # --- What the segmentation drew -------------------------------------
    Question(1, "Vùng AI tô khớp với ranh giới đốt sống và đĩa đệm trên phim.", "core", SEG),
    Question(2, "Màu và đường viền của vùng tô dễ nhìn, không che mất chi tiết tôi cần đọc.", "detail", SEG),
    Question(3, "Nhờ vùng tô, tôi xác định được tầng cần xem nhanh hơn.", "detail", SEG),

    # --- Whether the grades are right ------------------------------------
    Question(4, "Điểm chẩn đoán của AI khớp với đánh giá của tôi ở phần lớn các ca.", "core", GRADE),
    # Split by condition on purpose: the model is measurably weaker on
    # foraminal stenosis than on the others, so a single average would hide
    # exactly the disagreement worth reporting.
    Question(5, "Mức hẹp ống sống (canal stenosis) phù hợp với hình ảnh.", "detail", GRADE),
    Question(6, "Mức hẹp lỗ liên hợp (foraminal stenosis) phù hợp với hình ảnh.", "detail", GRADE),
    Question(7, "Phân độ thoái hoá đĩa đệm (Pfirrmann) phù hợp với hình ảnh.", "detail", GRADE),

    # --- Whether the presentation does any work ---------------------------
    Question(8, "Bảng kết quả theo từng tầng cho tôi nắm tình trạng cả đoạn cột sống trong một lần nhìn.", "detail", SHOW),
    Question(9, "Bấm vào một dòng để nhảy tới đúng lát cắt giúp tôi kiểm chứng nhanh hơn.", "detail", SHOW),
    Question(10, "Ảnh lát cắt AI đánh dấu giúp tôi hiểu nó đang căn cứ vào đâu.", "detail", SHOW),

    # --- How it fails, which accuracy alone cannot say --------------------
    Question(11, "Khi AI sai, mức sai lệch thường nhỏ và tôi dễ nhận ra.", "core", ERRORS),
    Question(12, "AI ít khi bỏ sót tổn thương nặng.", "detail", ERRORS),
    Question(13, "AI ít khi báo động giả ở ca bình thường.", "detail", ERRORS),

    # --- Whether it survives contact with a working day -------------------
    Question(14, "Việc sửa mask và sửa điểm diễn ra đúng như tôi mong đợi.", "detail", USE),
    Question(15, "Kết quả của AI đủ tin cậy để tham khảo khi đọc phim.", "detail", USE),
    Question(16, "Dùng công cụ này, tôi đọc xong một ca nhanh hơn so với đọc thủ công.", "detail", USE),
    Question(17, "Tôi sẵn sàng sử dụng công cụ này trong công việc thường ngày.", "core", USE),

    Question(18, "Phần mềm đáp ứng được nhu cầu công việc của tôi.", "usability", UX),
    Question(19, "Phần mềm dễ sử dụng.", "usability", UX),
]

CLINICAL_IDS = [q.id for q in QUESTIONS if q.kind in ("core", "detail")]
USABILITY_IDS = [q.id for q in QUESTIONS if q.kind == "usability"]
REQUIRED_IDS = [q.id for q in QUESTIONS if q.kind in REQUIRED_KINDS]
GROUPS = list(dict.fromkeys(q.group for q in QUESTIONS))

SCALE_MIN, SCALE_MAX = 1, 5
SCALE_LABELS = [
    "Rất không đồng ý",
    "Không đồng ý",
    "Trung lập",
    "Đồng ý",
    "Rất đồng ý",
]


def mean_of(answers: dict[int, int], ids: list[int]) -> float | None:
    """Mean over the ids actually answered, or None when none were.

    Averaging only what was answered is what makes skipping safe: a blank
    lowers nothing, so a clinician who did not look at foraminal crops is not
    quietly penalising the model for it.
    """
    values = [answers[i] for i in ids if i in answers]
    return round(sum(values) / len(values), 2) if values else None
