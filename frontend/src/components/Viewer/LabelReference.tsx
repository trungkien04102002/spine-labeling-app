import { CONDITIONS, CONDITION_ORDER } from "../../lib/clinicalTerms";

/**
 * What each of the eleven labels means and what each of its levels means.
 *
 * Built so a reader can check a grade against its definition without leaving
 * the study: the table above says "Độ 3", this says what Pfirrmann 3 looks
 * like. The source of every definition is stated at the bottom, and where the
 * published description and the network disagree, the card says so in amber
 * rather than quietly picking one.
 */
export default function LabelReference() {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {CONDITION_ORDER.map((key) => {
        const c = CONDITIONS[key];
        if (!c) return null;
        return (
          <section
            key={key}
            className="rounded-lg border border-slate-200 bg-white p-3"
          >
            <div className="flex flex-wrap items-baseline gap-x-2">
              <h3 className="text-sm font-bold text-slate-800">{c.full}</h3>
              <span className="text-xs text-slate-400">{c.en}</span>
              <span
                className={
                  "ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold " +
                  (c.source === "CBAM"
                    ? "bg-teal-50 text-teal-700"
                    : "bg-slate-100 text-slate-600")
                }
                title={
                  c.source === "CBAM"
                    ? "Mô hình CBAM tinh chỉnh của đề tài"
                    : "SpineNet (Oxford), mô hình gốc"
                }
              >
                {c.source === "CBAM" ? "Mô hình đề tài" : "SpineNet"}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-600">{c.definition}</p>
            <table className="mt-2 w-full text-xs">
              <tbody>
                {c.levels.map((l) => (
                  <tr key={l.value} className="border-t border-slate-100 align-top">
                    <td className="w-32 py-1 pr-2 font-semibold text-slate-700">
                      {l.vi}
                      <div className="font-mono text-[10px] font-normal text-slate-400">
                        {l.value}
                      </div>
                    </td>
                    <td className="py-1 text-slate-600">{l.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {c.caveat && (
              <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
                ⚠ {c.caveat}
              </p>
            )}
          </section>
        );
      })}
      <p className="text-[11px] leading-relaxed text-slate-400 lg:col-span-2">
        Nguồn: nhãn SpineNet theo Windsor và cs., <em>SpineNetV2</em>{" "}
        (arXiv 2205.01683), mục 4.3, đối chiếu với kiến trúc mạng và cách định
        dạng nhãn huấn luyện trong mã nguồn SpineNet; thang Pfirrmann theo
        Pfirrmann và cs., <em>Spine</em> 2001. Ba nhãn hẹp ống sống và hẹp lỗ
        liên hợp do mô hình của đề tài chấm, theo thang nhãn của bộ dữ liệu RSNA
        2024 Lumbar Spine Degenerative Classification.
      </p>
    </div>
  );
}
