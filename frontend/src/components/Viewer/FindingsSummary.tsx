import type { GradingItem } from "../../lib/api";
import { CONDITIONS, conditionHeader, severityLabel } from "../../lib/clinicalTerms";
import { useT } from "../../lib/i18n";
import ModelBadge from "./ModelBadge";

const LEVEL_ORDER = [
  "T10-T11",
  "T11-T12",
  "T12-L1",
  "L1-L2",
  "L2-L3",
  "L3-L4",
  "L4-L5",
  "L5-S1",
];

/**
 * How far up its own scale a value sits: 0 = normal, 1 = abnormal, 2 = marked.
 * The first step of every scale is normal; Pfirrmann 2 is too (normal height,
 * only an inhomogeneous disc), so a summary of "what is wrong" leaves it out.
 */
export function abnormality(condition: string, severity: string): 0 | 1 | 2 {
  const scale = CONDITIONS[condition]?.levels.map((l) => l.value);
  if (!scale) return 0;
  const i = scale.indexOf(severity);
  const normalUpTo = condition === "pfirrmann" ? 1 : 0;
  if (i <= normalUpTo) return 0;
  // The top of a scale, or the third step of a longer one, is the marked kind.
  return i === scale.length - 1 || i >= normalUpTo + 2 ? 2 : 1;
}

function levelRank(level: string): number {
  const i = LEVEL_ORDER.indexOf(level);
  return i === -1 ? LEVEL_ORDER.length : i;
}

/**
 * The abnormal findings, level by level, right beside the image.
 *
 * The full table sits below the viewer and is eleven rows by up to eight
 * columns; a reader had to scroll down to find what was wrong and back up to
 * look at it. This lists only what is not normal, worst first within a level,
 * and a click moves the image to that disc.
 */
export default function FindingsSummary({
  grading,
  original,
  onJump,
  onShowInTable,
}: {
  grading: GradingItem[];
  /** The AI's own grades, to mark what the doctor has changed. */
  original?: GradingItem[] | null;
  onJump: (slice: number) => void;
  /** Take the clinician to this level (or one finding) in the grade table. */
  onShowInTable?: (level: string, condition?: string) => void;
}) {
  const { t, lang } = useT();
  const aiValue = new Map(
    (original ?? []).map((g) => [`${g.level}/${g.condition}`, g.severity]),
  );

  const byLevel = new Map<string, GradingItem[]>();
  for (const g of grading) {
    if (abnormality(g.condition, g.severity) === 0) continue;
    if (!byLevel.has(g.level)) byLevel.set(g.level, []);
    byLevel.get(g.level)!.push(g);
  }
  const bboxOf = (level: string) => grading.find((g) => g.level === level && g.bbox)?.bbox ?? null;
  const levels = [...byLevel.keys()].sort((a, b) => levelRank(a) - levelRank(b));

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-1 flex items-center gap-2 text-base font-bold text-slate-800">
        <ModelBadge model="A" />
        {t("Model A — abnormal findings")}
      </h2>
      <p className="mb-3 text-xs text-slate-500">
        {t("Only what is not normal. Click a level, or one finding, to go to it in the model A table below — it will flash.")}
      </p>
      {levels.length === 0 ? (
        <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {t("Nothing abnormal at any level.")}
        </p>
      ) : (
        <ul className="space-y-2">
          {levels.map((level) => {
            const bbox = bboxOf(level);
            const items = byLevel
              .get(level)!
              .sort((a, b) => abnormality(b.condition, b.severity) - abnormality(a.condition, a.severity));
            return (
              <li key={level}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    if (bbox) onJump(bbox[0]);
                    onShowInTable?.(level);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      if (bbox) onJump(bbox[0]);
                      onShowInTable?.(level);
                    }
                  }}
                  className="w-full cursor-pointer rounded-md border border-slate-200 px-3 py-2 text-left transition hover:border-teal-400 hover:bg-teal-50"
                >
                  <div className="flex items-center justify-between text-sm font-bold text-slate-800">
                    {level}
                    <span className="text-xs font-medium text-teal-600">↓ {t("see in table")}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {items.map((g) => {
                      const marked = abnormality(g.condition, g.severity) === 2;
                      const edited =
                        aiValue.has(`${g.level}/${g.condition}`) &&
                        aiValue.get(`${g.level}/${g.condition}`) !== g.severity;
                      return (
                        <span
                          key={g.condition}
                          role="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (bbox) onJump(bbox[0]);
                            onShowInTable?.(g.level, g.condition);
                          }}
                          className={"cursor-pointer hover:brightness-95 " + 
                            "rounded px-1.5 py-0.5 text-xs font-medium " +
                            (marked ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800") +
                            (edited ? " ring-2 ring-indigo-400" : "")
                          }
                          title={edited ? t("Changed by you") : undefined}
                        >
                          {conditionHeader(g.condition, lang, CONDITIONS[g.condition]?.en ?? g.condition)}: {severityLabel(g.condition, g.severity, lang)}
                          {edited && " ✎"}
                        </span>
                      );
                    })}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/**
 * What this doctor changed on this study: every cell that now differs from the
 * AI's own grade, saved or not. The feedback panel only counted corrections,
 * so a doctor could not see which ones they had made.
 */
export function MyEdits({
  grading,
  original,
  unsaved,
  onRevert,
}: {
  grading: GradingItem[];
  original: GradingItem[];
  unsaved: boolean;
  /** Put these cells back to the AI's value (one undoable step). */
  onRevert?: (cells: { level: string; condition: string; severity: string }[]) => void;
}) {
  const { t, lang } = useT();
  const ai = new Map(original.map((g) => [`${g.level}/${g.condition}`, g.severity]));
  const edits = grading
    .filter((g) => ai.has(`${g.level}/${g.condition}`) && ai.get(`${g.level}/${g.condition}`) !== g.severity)
    .sort((a, b) => levelRank(a.level) - levelRank(b.level));

  return (
    <div className="mt-3 rounded-md border border-indigo-100 bg-indigo-50/50 p-3">
      <p className="text-xs font-semibold text-slate-700">{t("What you changed on this study")}</p>
      {edits.length === 0 ? (
        <p className="mt-1 text-xs text-slate-500">{t("Nothing yet — every grade is still the AI's.")}</p>
      ) : (
        <ul className="mt-1.5 space-y-1 text-xs text-slate-700">
          {edits.map((g) => (
            <li key={`${g.level}/${g.condition}`} className="flex flex-wrap items-center gap-x-2">
              <span>
                <span className="font-semibold">{g.level}</span> · {conditionHeader(g.condition, lang, CONDITIONS[g.condition]?.en ?? g.condition)}:{" "}
                <span className="text-slate-400 line-through">
                  {severityLabel(g.condition, ai.get(`${g.level}/${g.condition}`)!, lang)}
                </span>{" "}
                → <span className="font-semibold text-indigo-700">{severityLabel(g.condition, g.severity, lang)}</span>
              </span>
              {onRevert && (
                <button
                  type="button"
                  onClick={() =>
                    onRevert([{ level: g.level, condition: g.condition, severity: ai.get(`${g.level}/${g.condition}`)! }])
                  }
                  className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] font-medium text-slate-600 hover:border-indigo-400 hover:text-indigo-700"
                >
                  ↺ {t("Back to the AI's grade")}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {edits.length > 1 && onRevert && (
        <button
          type="button"
          onClick={() =>
            onRevert(edits.map((g) => ({ level: g.level, condition: g.condition, severity: ai.get(`${g.level}/${g.condition}`)! })))
          }
          className="mt-2 rounded border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-600 hover:border-indigo-400 hover:text-indigo-700"
        >
          ↺ {t("Put everything back to the AI's grades")}
        </button>
      )}
      {edits.length > 0 && unsaved && (
        <p className="mt-1.5 text-xs font-medium text-amber-700">
          {t("Not saved yet — press Save under the table. Undo (Ctrl+Z) also steps back.")}
        </p>
      )}
    </div>
  );
}
