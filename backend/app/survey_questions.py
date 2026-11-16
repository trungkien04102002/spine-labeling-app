"""The clinician questionnaire, focused on the quality of the model output.

Kinds: ``core`` and ``usability`` items are required; ``detail`` items may be
skipped (a blank is better than a guess); ``reference_b`` items ask about the
comparison model and are optional and excluded from the clinical score.
"""

from typing import Literal

Kind = Literal["usability", "core", "detail", "reference_b"]
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
        # Rendered as one row of a grid rather than as a separate block.
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
COMPARE = "Mô hình AI A và mô hình AI B theo từng tiêu chí"

# Question ids are permanent once any response exists: answers are stored as
# {id: score}, so renumbering silently re-labels stored answers. Add questions
# with new ids; retire an id by removing its question, never by reusing it.
# The ids are pinned by tests/test_survey.py.
QUESTIONS: list[Question] = [
    # Every item reads "aspect: what good looks like", so 5 is always the good
    # end. Never word an item negatively: that would silently invert its mean.

    # Segmentation quality.
    Question(1, "Vùng AI tô: bám đúng bờ đốt sống và đĩa đệm trên phim", "core", SEG),
    Question(2, "Màu và đường viền vùng tô: dễ nhìn, không che mất chi tiết trên phim", "detail", SEG),
    Question(3, "Vùng tô: giúp tìm nhanh tầng đĩa đệm cần xem", "detail", SEG),

    # Grading accuracy, overall and per label.
    Question(4, "Nhìn chung, điểm chẩn đoán của AI: khớp với đánh giá của tôi", "core", COMPARE),
    # One row per output label; left/right and upper/lower pairs are combined
    # because a reader judges them as one finding.
    Question(5, "Hẹp ống sống trung tâm (canal stenosis)", "detail", GRADE, matrix=True),
    Question(6, "Hẹp lỗ liên hợp trái / phải (foraminal stenosis)", "detail", GRADE, matrix=True),
    Question(7, "Thoái hoá đĩa đệm (Pfirrmann)", "detail", GRADE, matrix=True),
    Question(8, "Hẹp khe đĩa đệm (disc narrowing)", "detail", GRADE, matrix=True),
    Question(9, "Thoát vị đĩa đệm (disc herniation)", "detail", GRADE, matrix=True),
    Question(10, "Trượt đốt sống (spondylolisthesis)", "detail", GRADE, matrix=True),
    Question(11, "Tổn thương mâm sụn trên / dưới (endplate defect)", "detail", GRADE, matrix=True),
    Question(12, "Thay đổi Modic thân đốt trên / dưới (marrow)", "detail", GRADE, matrix=True),

    # Presentation.
    Question(13, "Bảng điểm: dễ đọc, xem nhanh được cả 5 tầng đĩa đệm", "detail", SHOW),
    Question(14, "Bấm vào tầng trong bảng, ảnh tự chuyển tới tầng đó: tiện đối chiếu với phim", "detail", SHOW),
    # Id 15 is retired and must not be reused.

    # Failure behaviour.
    Question(16, "Mức an toàn khi AI sai: chỉ lệch ít và tôi dễ nhận ra", "core", ERRORS),
    Question(17, "Tổn thương nặng: AI phát hiện được, không bỏ sót", "detail", COMPARE),
    Question(18, "Không báo nhầm: chỗ bình thường, AI cũng chấm là bình thường", "detail", COMPARE),

    # Use in clinical work.
    Question(19, "Sửa lại vùng tô và sửa điểm AI chấm: thuận tiện", "detail", USE),
    Question(20, "Kết quả AI: đủ tin cậy để tham khảo khi đọc phim", "detail", COMPARE),
    Question(21, "Thời gian đọc một ca: nhanh hơn so với tự đọc", "detail", USE),
    Question(22, "Dùng trong công việc thường ngày: phù hợp", "core", USE),

    Question(23, "Đáp ứng nhu cầu công việc của tôi", "usability", UX),
    Question(24, "Phần mềm: dễ sử dụng", "usability", UX),

    # Comparison model B, asked only while its panel is shown. Each item mirrors
    # one model-A item (MODEL_B_PAIRS) with the same wording so the means are
    # directly comparable. Never required, never counted in the clinical score.
    Question(25, "Kết quả mô hình AI B: khớp với đánh giá của tôi", "reference_b", COMPARE),
    Question(26, "Mô hình AI B, tổn thương nặng: phát hiện được, không bỏ sót", "reference_b", COMPARE),
    Question(27, "Mô hình AI B, không báo nhầm: chỗ bình thường, AI cũng chấm là bình thường", "reference_b", COMPARE),
    Question(28, "Kết quả mô hình AI B: đủ tin cậy để tham khảo khi đọc phim", "reference_b", COMPARE),
]

#: model B item -> the item asking the same of our own grades.
MODEL_B_PAIRS = {25: 4, 26: 17, 27: 18, 28: 20}

# Form sections, each a heading over its groups. Criteria asked of both models
# are shown with A directly above B so they are rated side by side.
SECTIONS = [
    ("Phần 1. Mô hình AI A: vùng tô và từng nhãn", [SEG, GRADE, ERRORS]),
    ("Phần 2. So sánh lâm sàng: mô hình AI A và mô hình AI B", [COMPARE]),
    ("Phần 3. Phần mềm", [SHOW, USE, UX]),
]
#: Part titles when model B is hidden: with one model there is no "A".
SECTION_TITLES_A_ONLY = {
    "Phần 1. Mô hình AI A: vùng tô và từng nhãn": "Phần 1. Kết quả AI: vùng tô và từng nhãn",
    "Phần 2. So sánh lâm sàng: mô hình AI A và mô hình AI B": "Phần 2. Đánh giá lâm sàng chung",
}
#: The COMPARE group's heading when model B is hidden.
COMPARE_GROUP_A_ONLY = "Độ chính xác và độ tin cậy của kết quả AI"

#: One criterion, asked of model A then model B, shown as a pair.
COMPARE_PAIRS = [
    ("Khớp với đánh giá của tôi", 4, 25),
    ("Tổn thương nặng: phát hiện được, không bỏ sót", 17, 26),
    ("Không báo nhầm: chỗ bình thường, AI cũng chấm là bình thường", 18, 27),
    ("Đủ tin cậy để tham khảo khi đọc phim", 20, 28),
]

CLINICAL_IDS = [q.id for q in QUESTIONS if q.kind in ("core", "detail")]
USABILITY_IDS = [q.id for q in QUESTIONS if q.kind == "usability"]
REQUIRED_IDS = [q.id for q in QUESTIONS if q.kind in REQUIRED_KINDS]
GROUPS = list(dict.fromkeys(q.group for q in QUESTIONS))

SCALE_MIN, SCALE_MAX = 1, 5
# A quality scale rather than agree/disagree, so no item needs reverse scoring.
SCALE_LABELS = [
    "Rất kém",
    "Kém",
    "Trung bình",
    "Tốt",
    "Rất tốt",
]


def mean_of(answers: dict[int, int], ids: list[int]) -> float | None:
    """Mean over the ids actually answered, or None when none were.

    Skipped items are excluded rather than counted, so a blank never lowers the score.
    """
    values = [answers[i] for i in ids if i in answers]
    return round(sum(values) / len(values), 2) if values else None
