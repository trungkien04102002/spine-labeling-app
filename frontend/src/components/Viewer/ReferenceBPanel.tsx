import { useEffect, useState } from "react";

import {
  getReferenceB,
  getReferenceBVisibility,
  referenceBInputUrl,
  runReferenceB,
  type ReferenceResult,
} from "../../lib/api";
import { useT } from "../../lib/i18n";

/**
 * A second model's answer, shown under the app's own grades for comparison.
 *
 * Hidden unless the operator switches it on in /admin (Model versions), so
 * clinicians see the app as it was unless asked to compare. Read-only and
 * self-contained: it never touches the grade table, and if model B is missing
 * or fails the panel just is not there -- the doctor's own flow must not
 * depend on it. Studies graded before model B
 * existed get it filled in the first time they are opened.
 */
export default function ReferenceBPanel({
  studyId,
  gradedAt,
}: {
  studyId: string;
  /** Changes whenever our grading re-runs, so the panel reloads with it. */
  gradedAt: unknown;
}) {
  const { t } = useT();
  const [result, setResult] = useState<ReferenceResult | null>(null);
  const [state, setState] = useState<"loading" | "running" | "ready" | "hidden">("loading");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    setResult(null);
    getReferenceBVisibility()
      .then((v) => {
        if (!v.visible || !v.installed) throw new Error("hidden");
        return getReferenceB(studyId);
      })
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        setState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        // Only "not run yet" is worth acting on; hidden, not installed, or
        // any failure means no panel.
        if (!/has not run/i.test(msg)) {
          setState("hidden");
          return;
        }
        setState("running");
        runReferenceB(studyId)
          .then((r) => {
            if (cancelled) return;
            setResult(r);
            setState("ready");
          })
          .catch(() => !cancelled && setState("hidden"));
      });
    return () => {
      cancelled = true;
    };
  }, [studyId, gradedAt]);

  if (state === "hidden" || state === "loading") return null;

  return (
    <div className="w-full basis-full rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-1 flex items-center gap-2 text-base font-bold text-slate-800">
        <span className="h-4 w-1 rounded bg-gradient-to-b from-slate-400 to-slate-500" />
        {t("For comparison: model B")}
      </h2>
      <p className="mb-3 text-xs text-slate-500">
        {t("Another AI model, run alongside for you to compare. It reads only one image (the middle slice, shown here) and answers for the whole image, not per disc level. It does not change the grades above.")}
      </p>
      {state === "running" || !result ? (
        <p className="text-sm text-slate-400">{t("Running model B…")}</p>
      ) : (
        <div className="flex flex-wrap gap-4">
          <figure className="w-40 shrink-0">
            <img
              src={referenceBInputUrl(studyId, result.created_at)}
              alt={t("Image model B read")}
              className="w-full rounded border border-slate-200 bg-black"
            />
            <figcaption className="mt-1 text-[11px] text-slate-400">
              {t("Slice {i} of {n}", { i: result.slice_index + 1, n: result.slice_count })}
            </figcaption>
          </figure>
          <div className="min-w-[240px] flex-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="py-1.5 font-semibold">{t("Finding")}</th>
                  <th className="py-1.5 font-semibold">{t("Probability")}</th>
                  <th className="py-1.5 text-right font-semibold">{t("Result")}</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((r) => (
                  <tr key={r.label} className="border-b border-slate-100">
                    <td className="py-1.5 text-slate-700">{t(r.label)}</td>
                    <td className="py-1.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded bg-slate-100">
                          <div
                            className="h-full bg-slate-400"
                            style={{ width: `${Math.round(r.probability * 100)}%` }}
                          />
                        </div>
                        <span className="text-xs tabular-nums text-slate-500">
                          {Math.round(r.probability * 100)}%
                        </span>
                      </div>
                    </td>
                    <td
                      className={
                        "py-1.5 text-right font-semibold " +
                        (r.prediction ? "text-rose-600" : "text-emerald-600")
                      }
                    >
                      {r.prediction ? t("Yes") : t("No")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {result.no_finding_override && (
              <p className="mt-2 text-xs text-slate-500">
                {t("“No finding” scored highest, so model B counts every other finding as No.")}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
