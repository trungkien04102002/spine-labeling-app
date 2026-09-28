import { useEffect, useState, type ReactNode } from "react";
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

const SCALE_HINT = "1 = rất kém · 5 = rất tốt";

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
  const required = question.required;
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

/**
 * Several items on the same scale as one grid: a row per label, a column per
 * score. Eight labels as eight separate button rows would triple the length of
 * the page for no extra information, and a column is quicker to scan.
 */
function QuestionMatrix({
  questions,
  labels,
  answers,
  onChange,
}: {
  questions: SurveyQuestion[];
  labels: string[];
  answers: Record<number, number>;
  onChange: (id: number, value: number) => void;
}) {
  return (
    <div className="mt-3 border-t border-slate-200 pt-3">
      <p className="mb-2 text-sm text-slate-800">
        Độ chính xác theo từng nhãn{" "}
        <span className="text-xs text-slate-400">
          (bỏ qua nhãn bác sĩ chưa xem kỹ)
        </span>
      </p>
      <div className="scroll-x-visible">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr>
              <th />
              {labels.map((label, i) => (
                <th
                  key={label}
                  className="px-1 pb-1 text-center text-[11px] font-medium leading-tight text-slate-500"
                >
                  <div className="font-bold text-slate-700">{i + 1}</div>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {questions.map((q) => (
              <tr key={q.id} className="border-t border-slate-100">
                <th
                  scope="row"
                  className="py-2 pr-3 text-left text-[13px] font-normal text-slate-700"
                >
                  {q.text}
                </th>
                {labels.map((label, i) => {
                  const score = i + 1;
                  const selected = answers[q.id] === score;
                  return (
                    <td key={score} className="px-1 py-1 text-center">
                      <button
                        type="button"
                        aria-pressed={selected}
                        aria-label={`${q.text}: ${score} — ${label}`}
                        onClick={() => onChange(q.id, score)}
                        className={
                          "h-8 w-full min-w-[44px] rounded-md border text-sm transition " +
                          (selected
                            ? "border-teal-500 bg-teal-500 font-bold text-white"
                            : "border-slate-200 bg-white text-slate-500 hover:border-teal-300")
                        }
                      >
                        {score}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Same teal bar as the worklist and viewer, with the way back. */
function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="bg-gradient-to-r from-teal-600 to-cyan-500 shadow-md">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3.5">
          <Link
            to="/"
            className="rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium text-white backdrop-blur transition hover:bg-white/25"
          >
            ← Danh sách ca
          </Link>
          <div className="text-sm font-bold text-white">Đánh giá phần mềm</div>
        </div>
      </header>
      {children}
    </div>
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

  const required = (form?.questions ?? []).filter((q) => q.required);
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
      <Shell>
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h1 className="text-xl font-bold text-slate-800">Đã ghi nhận. Cảm ơn bác sĩ.</h1>
        <p className="mt-2 text-sm text-slate-600">
          Ý kiến của bác sĩ được lưu ẩn danh trừ phần bác sĩ tự điền tên.
        </p>
        <Link to="/" className="mt-6 inline-block text-sm text-teal-700 underline">
          Quay lại danh sách ca
        </Link>
      </div>
      </Shell>
    );
  }

  return (
    <Shell>
    <div className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-xl font-bold text-slate-800">Phiếu đánh giá phần mềm</h1>
      <p className="mt-2 text-sm text-slate-600">
        Khoảng 5 phút. Bác sĩ chấm từng mặt của kết quả AI — vùng tô, điểm
        chẩn đoán của cả 11 nhãn, kiểu sai, cách trình bày — {SCALE_HINT}.
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

      {(form?.groups ?? []).map((group) => (
        <section
          key={group}
          className="mt-5 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        >
          {/* Grouped so sixteen questions read as four short topics rather
              than one long column: a clinician can see where they are. */}
          <h2 className="mb-1 flex items-center gap-2 text-sm font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
            {group}
          </h2>
          {(form?.questions ?? [])
            .filter((q) => q.group === group && !q.matrix)
            .map((q) => (
              <QuestionRow
                key={q.id}
                question={q}
                index={q.id - 1}
                labels={form!.scale.labels}
                value={answers[q.id]}
                onChange={(v) => setAnswers((prev) => ({ ...prev, [q.id]: v }))}
              />
            ))}
          {(() => {
            const grid = (form?.questions ?? []).filter(
              (q) => q.group === group && q.matrix,
            );
            return grid.length > 0 ? (
              <QuestionMatrix
                questions={grid}
                labels={form!.scale.labels}
                answers={answers}
                onChange={(id, v) => setAnswers((prev) => ({ ...prev, [id]: v }))}
              />
            ) : null;
          })()}
        </section>
      ))}

      <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="pt-1">
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
    </Shell>
  );
}
