import { CONDITIONS, CONDITION_ORDER } from "../../lib/clinicalTerms";

/**
 * What each of the eleven labels means and what each of its levels means.
 *
 * Built so a reader can check a grade against its definition without leaving
 * the study: the table above says "Độ 3", this says what Pfirrmann 3 looks
 * like. Clinical meaning only: which model or dataset produced a label is
 * operator information and stays out of the doctor's page (sources are in
 * the header comment of clinicalTerms.ts).
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
    </div>
  );
}
