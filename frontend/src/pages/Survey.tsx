import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  getSurveyForm,
  submitSurvey,
  type SurveyForm,
  type SurveyQuestion,
} from "../lib/api";

/**
 * The clinician questionnaire.
 *
 * Vietnamese throughout, unlike the rest of the UI: the people answering read
 * Vietnamese, and a usability score collected through a language barrier
 * measures the barrier. The ten usability items are the System Usability
 * Scale, whose wording is fixed -- rephrasing them would leave a number that
 * no longer compares to anything published.
 */

const SCALE_HINT = "1 = rất không đồng ý · 5 = rất đồng ý";

function QuestionRow({
  question,
  index,
  labels,
  value,
  onChange,
}: {
  question: SurveyQuestion;
  index: number;
  labels: string[];
  value: number | undefined;
  onChange: (value: number) => void;
}) {
  const required = question.kind !== "domain";
  return (
    <fieldset className="border-t border-slate-200 py-4 first:border-t-0">
      <legend className="sr-only">{question.text}</legend>
      <p className="mb-3 text-sm text-slate-800">
        <span className="mr-2 font-semibold text-slate-400">{index + 1}.</span>
        {question.text}
        {!required && (
          <span className="ml-2 text-xs text-slate-400">(có thể bỏ qua)</span>
        )}
      </p>
      <div className="flex flex-wrap gap-2">
        {labels.map((label, i) => {
          const score = i + 1;
          const selected = value === score;
          return (
            <button
              key={score}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(score)}
              className={
                "flex min-w-[104px] flex-1 flex-col items-center rounded-lg border px-2 py-2 text-xs transition " +
                (selected
                  ? "border-teal-500 bg-teal-50 font-semibold text-teal-800"
                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-300")
              }
            >
              <span className="text-sm font-bold">{score}</span>
              <span className="mt-0.5 text-center leading-tight">{label}</span>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export default function Survey() {
  const [form, setForm] = useState<SurveyForm | null>(null);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [respondent, setRespondent] = useState("");
  const [role, setRole] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    getSurveyForm()
      .then(setForm)
      .catch(() => setError("Không tải được bộ câu hỏi. Thử tải lại trang."));
  }, []);

  const required = (form?.questions ?? []).filter((q) => q.kind !== "domain");
  const answeredRequired = required.filter((q) => answers[q.id] != null).length;
  const canSubmit = form != null && answeredRequired === required.length && !sending;

  async function handleSubmit() {
    setSending(true);
    setError(null);
    try {
      await submitSurvey({
        answers,
        respondent: respondent.trim() || undefined,
        role: role.trim() || undefined,
        comment: comment.trim() || undefined,
      });
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gửi không thành công.");
    } finally {
      setSending(false);
    }
  }

  if (done) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h1 className="text-xl font-bold text-slate-800">Đã ghi nhận. Cảm ơn bác sĩ.</h1>
        <p className="mt-2 text-sm text-slate-600">
          Ý kiến của bác sĩ được lưu ẩn danh trừ phần bác sĩ tự điền tên.
        </p>
        <Link to="/" className="mt-6 inline-block text-sm text-teal-700 underline">
          Quay lại danh sách ca
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-xl font-bold text-slate-800">Phiếu đánh giá phần mềm</h1>
      <p className="mt-2 text-sm text-slate-600">
        15 câu, khoảng 3 phút. Mười câu đầu về mức dễ dùng, năm câu sau về kết
        quả chẩn đoán. {SCALE_HINT}.
      </p>
      <p className="mt-1 text-sm text-slate-500">
        Không có câu trả lời đúng hay sai — đánh giá thấp cũng có ích như đánh
        giá cao.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {error}
        </div>
      )}

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        {(form?.questions ?? []).map((q, i) => (
          <QuestionRow
            key={q.id}
            question={q}
            index={i}
            labels={form!.scale.labels}
            value={answers[q.id]}
            onChange={(v) => setAnswers((prev) => ({ ...prev, [q.id]: v }))}
          />
        ))}

        <div className="border-t border-slate-200 pt-4">
          <label className="block text-sm text-slate-800" htmlFor="comment">
            Góp ý thêm (không bắt buộc)
          </label>
          <textarea
            id="comment"
            rows={3}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            placeholder="Điều gì khiến bác sĩ khó chịu nhất khi dùng?"
          />
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <input
              value={respondent}
              onChange={(e) => setRespondent(e.target.value)}
              placeholder="Họ tên (không bắt buộc)"
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
            <input
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="Chuyên khoa / vị trí (không bắt buộc)"
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between gap-4">
        <span className="text-sm text-slate-500">
          Đã trả lời {answeredRequired}/{required.length} câu bắt buộc
        </span>
        <button
          type="button"
          disabled={!canSubmit}
          onClick={handleSubmit}
          className="rounded-lg bg-teal-600 px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {sending ? "Đang gửi…" : "Gửi đánh giá"}
        </button>
      </div>
    </div>
  );
}
