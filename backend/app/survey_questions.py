"""The clinician questionnaire: ten SUS items, five about this tool.

The first ten are the System Usability Scale (Brooke, 1996) in Vietnamese.
They are not ours to reword: SUS only yields a comparable number because every
study asks the same ten things in the same order, alternating positive and
negative so that agreeing with everything scores nothing. That comparability is
the whole reason for using it -- "SUS 74" sits against a published mean of 68,
where "4.1 out of 5" sits against nothing.

The last five are specific to this tool and are what the supervisor actually
asked for. They are all positively worded, so they average directly.
"""

from typing import Literal

Kind = Literal["sus_positive", "sus_negative", "domain"]


class Question:
    __slots__ = ("id", "text", "kind")

    def __init__(self, id: int, text: str, kind: Kind) -> None:
        self.id = id
        self.text = text
        self.kind = kind

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "text": self.text, "kind": self.kind}


QUESTIONS: list[Question] = [
    # --- System Usability Scale, standard order --------------------------
    Question(1, "Tôi nghĩ tôi sẽ muốn sử dụng hệ thống này thường xuyên.", "sus_positive"),
    Question(2, "Tôi thấy hệ thống này phức tạp một cách không cần thiết.", "sus_negative"),
    Question(3, "Tôi thấy hệ thống này dễ sử dụng.", "sus_positive"),
    Question(4, "Tôi nghĩ tôi cần người hỗ trợ kỹ thuật mới dùng được hệ thống này.", "sus_negative"),
    Question(5, "Tôi thấy các chức năng trong hệ thống gắn kết tốt với nhau.", "sus_positive"),
    Question(6, "Tôi thấy hệ thống này có quá nhiều điểm thiếu nhất quán.", "sus_negative"),
    Question(7, "Tôi nghĩ hầu hết mọi người sẽ học dùng hệ thống này rất nhanh.", "sus_positive"),
    Question(8, "Tôi thấy hệ thống này rườm rà, khó thao tác.", "sus_negative"),
    Question(9, "Tôi cảm thấy tự tin khi sử dụng hệ thống này.", "sus_positive"),
    Question(10, "Tôi cần học rất nhiều thứ trước khi có thể bắt đầu dùng hệ thống này.", "sus_negative"),
    # --- About this tool in particular -----------------------------------
    Question(11, "Kết quả phân vùng đốt sống và đĩa đệm khớp với đánh giá của tôi.", "domain"),
    Question(12, "Điểm chẩn đoán của AI khớp với đánh giá của tôi ở phần lớn các ca.", "domain"),
    # Asked separately from accuracy because they are different failures. A
    # model that is one grade out on a borderline disc is usable; one that
    # calls a severe stenosis normal is not, and both can sit at the same
    # accuracy. Which of the two it does is what decides whether a radiologist
    # can leave it running.
    Question(13, "Khi AI sai, mức sai lệch thường nhỏ và tôi dễ nhận ra.", "domain"),
    Question(14, "Điểm chẩn đoán của AI đủ tin cậy để tham khảo khi đọc phim.", "domain"),
    Question(15, "Việc sửa mask và sửa điểm diễn ra đúng như tôi mong đợi.", "domain"),
    Question(16, "Công cụ này rút ngắn thời gian đọc một ca.", "domain"),
    Question(17, "Tôi sẵn sàng sử dụng công cụ này trong công việc thường ngày.", "domain"),
]

SUS_IDS = [q.id for q in QUESTIONS if q.kind != "domain"]
DOMAIN_IDS = [q.id for q in QUESTIONS if q.kind == "domain"]
_KIND_BY_ID = {q.id: q.kind for q in QUESTIONS}

SCALE_MIN, SCALE_MAX = 1, 5
SCALE_LABELS = [
    "Rất không đồng ý",
    "Không đồng ý",
    "Trung lập",
    "Đồng ý",
    "Rất đồng ý",
]


def sus_score(answers: dict[int, int]) -> float:
    """Score the ten SUS items onto 0-100.

    Each item contributes its distance from the worst possible answer -- for a
    positively worded item that is ``value - 1``, for a negatively worded one
    ``5 - value`` -- giving 0-4 per item, 0-40 in total, scaled by 2.5. The
    result is a percentile-like number, not a percentage: 68 is the published
    average across studies, and roughly 85 is the top decile.
    """
    total = 0
    for qid in SUS_IDS:
        value = answers[qid]
        total += (value - SCALE_MIN) if _KIND_BY_ID[qid] == "sus_positive" else (SCALE_MAX - value)
    return round(total * 2.5, 1)
