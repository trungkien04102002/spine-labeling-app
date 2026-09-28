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
    __slots__ = ("id", "text", "kind", "group", "matrix")

    def __init__(
        self, id: int, text: str, kind: Kind, group: str, matrix: bool = False
    ) -> None:
        self.id = id
        self.text = text
        self.kind = kind
        self.group = group
        # Rendered as one row of a grid rather than as its own block: eight
        # labels rated on the same scale are read faster down a column.
        self.matrix = matrix

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "group": self.group,
            "required": self.kind in REQUIRED_KINDS,
            "matrix": self.matrix,
        }


SEG = "Vùng AI tô trên phim"
GRADE = "Điểm chẩn đoán"
ERRORS = "Khi AI sai"
SHOW = "Cách trình bày kết quả"
USE = "Sử dụng trong công việc"
UX = "Đánh giá chung về phần mềm"

# QUESTION IDS ARE PERMANENT ONCE ANY RESPONSE EXISTS. Answers are stored as
# {id: score}, so renumbering silently re-labels every answer already given:
# on 2026-09-28 a response taken under the 19-question draft started showing
# its "results table" score under "disc narrowing". To add a question, give it
# a new id; to drop one, stop showing it but never hand its id to another. The
# frozen ids below are pinned by tests/test_survey.py.
QUESTIONS: list[Question] = [
    # Every item reads "aspect: what good looks like", rated from very poor to
    # very good, so 5 is always the good end. Plain words a clinician uses --
    # no "mask", no "Mức X giúp tôi..." constructions translated from English,
    # which a doctor in the trial found hard to parse. Never word one
    # negatively ("AI often misses..."): that would silently invert its mean.

    # --- What the segmentation drew -------------------------------------
    Question(1, "Vùng AI tô: bám đúng bờ đốt sống và đĩa đệm trên phim", "core", SEG),
    Question(2, "Màu và đường viền vùng tô: dễ nhìn, không che mất chi tiết trên phim", "detail", SEG),
    Question(3, "Vùng tô: giúp tìm nhanh tầng đĩa đệm cần xem", "detail", SEG),

    # --- Whether the grades are right, overall and label by label -----------
    Question(4, "Nhìn chung, điểm chẩn đoán của AI: khớp với đánh giá của tôi", "core", GRADE),
    # One row per label the app actually outputs -- all eleven, with left and
    # right foraminal, and upper and lower endplate and marrow, taken
    # together because a reader judges a side or an edge as one finding.
    # Asking only about the thesis model's three would leave the eight
    # SpineNet columns, most of the table, with no clinical opinion at all.
    Question(5, "Hẹp ống sống trung tâm (canal stenosis)", "detail", GRADE, matrix=True),
    Question(6, "Hẹp lỗ liên hợp trái / phải (foraminal stenosis)", "detail", GRADE, matrix=True),
    Question(7, "Thoái hoá đĩa đệm (Pfirrmann)", "detail", GRADE, matrix=True),
    Question(8, "Hẹp khe đĩa (disc narrowing)", "detail", GRADE, matrix=True),
    Question(9, "Thoát vị đĩa đệm (disc herniation)", "detail", GRADE, matrix=True),
    Question(10, "Trượt đốt sống (spondylolisthesis)", "detail", GRADE, matrix=True),
    Question(11, "Tổn thương tấm tận trên / dưới (endplate defect)", "detail", GRADE, matrix=True),
    Question(12, "Thay đổi tuỷ xương trên / dưới — Modic (marrow)", "detail", GRADE, matrix=True),

    # --- Whether the presentation does any work ---------------------------
    Question(13, "Bảng kết quả (mỗi cột là một tầng đĩa đệm): xem nhanh được cả cột sống thắt lưng", "detail", SHOW),
    Question(14, "Bấm vào một tầng trong bảng để ảnh chuyển tới tầng đó: giúp đối chiếu kết quả với phim", "detail", SHOW),
    # 15 asked about the SpineNet-labelled slice image, removed from the viewer
    # 2026-09-28 as taking space for no value. Retired, never to be reused.

    # --- How it fails, which accuracy alone cannot say --------------------
    Question(16, "Mức an toàn khi AI sai: chỉ lệch ít và tôi dễ nhận ra", "core", ERRORS),
    Question(17, "Tổn thương nặng: AI phát hiện được, không bỏ sót", "detail", ERRORS),
    Question(18, "Ca bình thường: AI không báo bệnh nhầm", "detail", ERRORS),

    # --- Whether it survives contact with a working day -------------------
    Question(19, "Sửa lại vùng tô và sửa điểm AI chấm: thuận tiện", "detail", USE),
    Question(20, "Kết quả AI: đủ tin cậy để tham khảo khi đọc phim", "detail", USE),
    Question(21, "Thời gian đọc một ca: nhanh hơn so với tự đọc", "detail", USE),
    Question(22, "Dùng trong công việc thường ngày: phù hợp", "core", USE),

    Question(23, "Đáp ứng nhu cầu công việc của tôi", "usability", UX),
    Question(24, "Phần mềm: dễ sử dụng", "usability", UX),
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
