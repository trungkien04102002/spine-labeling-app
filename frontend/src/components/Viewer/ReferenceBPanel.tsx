import { useEffect, useState } from "react";

import {
  getReferenceB,
  getReferenceBVisibility,
  referenceBInputUrl,
  runReferenceB,
  type ReferenceResult,
} from "../../lib/api";
import type { GradingItem } from "../../lib/api";
import { useT } from "../../lib/i18n";
import ModelBadge from "./ModelBadge";
import { abnormality } from "./FindingsSummary";

/**
 * Model B's whole-image labels against model A's per-level conditions, so a
 * clinician can read the two side by side. A label with no counterpart in
 * model A (disc bulging) maps to nothing and shows a dash.
 */
const A_CONDITIONS: Record<string, string[]> = {
  "UP endplate": ["upper_endplate_defect"],
  "LOW endplate": ["lower_endplate_defect"],
  Spondylolisthesis: ["spondylolisthesis"],
  "Disc herniation": ["disc_herniation"],
  "Disc narrowing": ["disc_narrowing"],
  Modic: ["upper_marrow", "lower_marrow"],
};

const LEVELS = ["T10-T11", "T11-T12", "T12-L1", "L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1"];

/** Model A's answer for one model-B label: yes + the levels, no, or null. */
function modelAAnswer(label: string, grading: GradingItem[]): { yes: boolean; levels: string[] } | null {
  if (label === "No Finding") {
    const any = grading.some((g) => abnormality(g.condition, g.severity) > 0);
    return { yes: !any, levels: [] };
  }
  const conditions = A_CONDITIONS[label];
  if (!conditions) return null;
  const levels = [
    ...new Set(
      grading
        .filter((g) => conditions.includes(g.condition) && abnormality(g.condition, g.severity) > 0)
        .map((g) => g.level),
    ),
  ].sort((a, b) => LEVELS.indexOf(a) - LEVELS.indexOf(b));
  return { yes: levels.length > 0, levels };
}

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
  modelA,
  alwaysShow = false,
}: {
  studyId: string;
  /** Changes whenever our grading re-runs, so the panel reloads with it. */
  gradedAt: unknown;
  /** Model A's current grades (with the doctor's edits), for the A column. */
  modelA?: GradingItem[] | null;
  /** Ignore the /admin switch (an uploaded picture, which only model B reads). */
  alwaysShow?: boolean;
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
        if (!v.installed || (!v.visible && !alwaysShow)) throw new Error("hidden");
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
  }, [studyId, gradedAt, alwaysShow]);

  async function rerun(plane: "sagittal" | "axial") {
    setState("running");
    try {
      setResult(await runReferenceB(studyId, plane));
      setState("ready");
    } catch {
      setState("hidden");
    }
  }

  if (state === "hidden" || state === "loading") return null;

  return (
    <div id="model-b" className="w-full basis-full scroll-mt-4 rounded-lg border-2 border-violet-200 bg-white p-4 shadow-sm">
      <h2 className="mb-1 flex items-center gap-2 text-base font-bold text-slate-800">
        <ModelBadge model="B" />
        {t("Model B — results to compare")}
        <span className="text-xs font-normal text-slate-500">{t("(not editable)")}</span>
      </h2>
      <p className="mb-3 text-xs text-slate-500">
        {result?.source === "picture"
          ? t("Model B reads the uploaded picture and answers yes/no for the whole image. Say whether the picture is a side view (sagittal) or a cross-section (axial): model B has a version for each.")
          : t("A second AI model, run on the same study. It reads one image (the middle slice, shown here) and answers yes/no for the whole image, not per disc level. The “Model A” column is model A's answer for the same finding: yes if it found it at any level.")}
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
              {result.source === "picture"
                ? t("The uploaded picture")
                : t("Slice {i} of {n}", { i: result.slice_index + 1, n: result.slice_count })}
            </figcaption>
          </figure>
          <div className="min-w-[240px] flex-1">
            {result.source === "picture" && (
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                {t("This picture is a:")}
                {(["sagittal", "axial"] as const).map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => result.plane !== p && void rerun(p)}
                    className={
                      "rounded-md border px-2.5 py-1 font-semibold " +
                      (result.plane === p
                        ? "border-teal-500 bg-teal-600 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:border-teal-400")
                    }
                  >
                    {p === "sagittal" ? t("Sagittal (side view)") : t("Axial (cross-section)")}
                  </button>
                ))}
              </div>
            )}
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="py-1.5 font-semibold">{t("Finding")}</th>
                  <th className="py-1.5 font-semibold">{t("Model B: probability")}</th>
                  <th className="py-1.5 text-right font-semibold">{t("Model B")}</th>
                  {modelA && <th className="py-1.5 pl-4 text-right font-semibold">{t("Model A")}</th>}
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
                    {modelA && (() => {
                      const a = modelAAnswer(r.label, modelA);
                      if (!a) {
                        return (
                          <td className="py-1.5 pl-4 text-right text-slate-300" title={t("Model A has no matching finding")}>
                            —
                          </td>
                        );
                      }
                      return (
                        <td className={"py-1.5 pl-4 text-right font-semibold " + (a.yes ? "text-rose-600" : "text-emerald-600")}>
                          {a.yes ? t("Yes") : t("No")}
                          {a.levels.length > 0 && (
                            <span className="ml-1 text-[11px] font-normal text-slate-500">({a.levels.join(", ")})</span>
                          )}
                        </td>
                      );
                    })()}
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
