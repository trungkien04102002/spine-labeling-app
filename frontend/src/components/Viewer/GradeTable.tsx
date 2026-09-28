import { useCallback, useEffect, useRef, useState } from "react";
import type { GradingItem } from "../../lib/api";
import { useT } from "../../lib/i18n";
import { CONDITIONS, conditionHeader, severityLabel } from "../../lib/clinicalTerms";
import {
  isTrainableCondition,
  severityOptions,
} from "../../lib/severityVocabulary";

// Ordering *hints* only — anything the model returns that isn't listed still
// shows, appended after the known ones. This keeps the table correct when the
// model gains new levels or conditions (e.g. pfirrmann, disc_herniation).
const LEVEL_ORDER = [
  "L1-L2",
  "L2-L3",
  "L3-L4",
  "L4-L5",
  "L5-S1",
];
// The 3 CBAM-sourced conditions first, then the 8 SpineNet-sourced ones, in
// roughly the order the Oxford SpineNet demo presents them.
const CONDITION_ORDER = [
  "canal_stenosis",
  "left_foraminal",
  "right_foraminal",
  "pfirrmann",
  "disc_narrowing",
  "disc_herniation",
  "spondylolisthesis",
  "upper_endplate_defect",
  "lower_endplate_defect",
  "upper_marrow",
  "lower_marrow",
];
const CONDITION_LABELS: Record<string, string> = {
  canal_stenosis: "Canal",
  left_foraminal: "L. foraminal",
  right_foraminal: "R. foraminal",
  pfirrmann: "Pfirrmann",
  disc_narrowing: "Disc narrowing",
  disc_herniation: "Disc herniation",
  spondylolisthesis: "Spondylolisthesis",
  upper_endplate_defect: "Upper endplate defect",
  lower_endplate_defect: "Lower endplate defect",
  upper_marrow: "Upper marrow",
  lower_marrow: "Lower marrow",
};
const LOW_CONFIDENCE = 0.5;
/** Marks a column whose corrections the re-training loop does not consume. */
const NOT_TRAINED_MARK = "†";

/** Prettify an unknown condition key, e.g. "disc_herniation" -> "Disc herniation". */
function conditionLabel(key: string): string {
  return (
    CONDITION_LABELS[key] ??
    key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
}

/** Cell tint for a severity label (light theme; neutral for unknown scales). */
function severityColor(severity: string): string {
  if (severity === "Severe" || severity === "Present") return "#fde2e2";
  if (severity === "Moderate" || severity === "Grade II" || severity === "Grade 3") {
    return "#fdefc7";
  }
  if (severity === "Grade 4" || severity === "Grade 5") return "#fde2e2";
  if (severity === "Normal/Mild" || severity === "Absent" || severity === "None") {
    return "#e3f2e3";
  }
  return "#f1f3f5"; // unknown severity scale (e.g. a bare Pfirrmann/narrowing grade)
}

/** Order values by a hint list first, then append the rest (natural sort). */
function ordered(values: string[], hint: string[]): string[] {
  const known = hint.filter((v) => values.includes(v));
  const extra = values
    .filter((v) => !hint.includes(v))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  return [...known, ...extra];
}

interface Props {
  grading: GradingItem[];
  /** Called with a slice index when a level row is clicked (jump-to-disc). */
  onJump: (slice: number) => void;
  /** When set, each cell shows a severity dropdown that calls this on change. */
  onEditSeverity?: (level: string, condition: string, severity: string) => void;
}

/**
 * Per-disc abnormality grades: one row per level, one column per condition,
 * derived dynamically from whatever the model returns. Cells are color-coded by
 * severity; low-confidence predictions get a ⚠ marker (full score on hover).
 * Clicking a row scrolls the viewer to that disc.
 */
/**
 * True for a stored value its condition's head cannot produce -- a legacy
 * correction or a merge that let the wrong model's value through. Such a cell
 * used to look exactly like a valid one ("Absent" under right foraminal, whose
 * scale is Normal/Mild · Moderate · Severe), so nobody fixed it; re-training
 * then drops it silently. It is flagged where it is read instead.
 */
function outOfScale(condition: string, value: string): boolean {
  const scale = CONDITIONS[condition]?.levels;
  return scale != null && !scale.some((l) => l.value === value);
}

export default function GradeTable({ grading, onJump, onEditSeverity }: Props) {
  const { t, lang } = useT();
  // Eleven condition columns do not fit a laptop screen. Track whether there
  // is more to either side, so the controls and the edge fade only appear when
  // they mean something.
  const scroller = useRef<HTMLDivElement | null>(null);
  const [more, setMore] = useState({ left: false, right: false });
  const measure = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    setMore({
      left: el.scrollLeft > 4,
      right: el.scrollLeft + el.clientWidth < el.scrollWidth - 4,
    });
  }, []);
  useEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure, grading, lang]);
  const nudge = (direction: 1 | -1) =>
    scroller.current?.scrollBy({
      left: direction * scroller.current.clientWidth * 0.6,
      behavior: "smooth",
    });
  // Index by level+condition, and collect the distinct levels/conditions.
  const byLevel = new Map<string, Map<string, GradingItem>>();
  const conditionSet = new Set<string>();
  for (const item of grading) {
    if (!byLevel.has(item.level)) byLevel.set(item.level, new Map());
    byLevel.get(item.level)!.set(item.condition, item);
    conditionSet.add(item.condition);
  }

  const levels = ordered([...byLevel.keys()], LEVEL_ORDER);
  const conditions = ordered([...conditionSet], CONDITION_ORDER);
  // Each condition gets its own scale: "Upper endplate defect" is only ever
  // Absent/Present, and offering it Moderate produced corrections the training
  // set silently drops. See lib/severityVocabulary.ts. A condition that file
  // does not know falls back to the values this study holds for it, so a
  // condition the backend adds stays editable.
  const seenByCondition = new Map<string, Set<string>>();
  for (const item of grading) {
    if (!seenByCondition.has(item.condition)) {
      seenByCondition.set(item.condition, new Set());
    }
    seenByCondition.get(item.condition)!.add(item.severity);
  }
  const optionsByCondition = new Map<string, string[]>(
    conditions.map((c) => [
      c,
      severityOptions(c, seenByCondition.get(c) ?? []),
    ]),
  );
  // Only worth a footnote when the table actually shows such a column.
  const hasUntrainedColumn = conditions.some((c) => !isTrainableCondition(c));

  return (
    <>
    {(more.left || more.right) && (
      <div className="mb-1.5 flex items-center justify-end gap-2 text-[11px] text-slate-500">
        <span className="mr-auto">{t("More columns to the side — use the arrows, drag the bar, or Shift + scroll.")}</span>
        <button
          type="button"
          onClick={() => nudge(-1)}
          disabled={!more.left}
          aria-label={t("Scroll left")}
          className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-30"
        >
          ◀
        </button>
        <button
          type="button"
          onClick={() => nudge(1)}
          disabled={!more.right}
          aria-label={t("Scroll right")}
          className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-30"
        >
          ▶
        </button>
      </div>
    )}
    <div style={{ position: "relative" }}>
    <div ref={scroller} onScroll={measure} className="scroll-x-visible">
    <table
      style={{
        borderCollapse: "collapse",
        fontSize: "0.85rem",
        width: "100%",
      }}
    >
      <thead>
        <tr>
          <th
            style={{
              textAlign: "left",
              padding: "4px 8px",
              position: "sticky",
              left: 0,
              background: "#fff",
              zIndex: 1,
            }}
          >
            {t("Level")}
          </th>
          {conditions.map((c) => (
            <th
              key={c}
              style={{ padding: "4px 8px", verticalAlign: "bottom", minWidth: 96 }}
            >
              {conditionHeader(c, lang, conditionLabel(c))}
              {!isTrainableCondition(c) && (
                <span
                  title={t("Graded by the vendored upstream SpineNet. Corrections here are saved and exported, but re-training does not use them.")}
                  style={{ color: "#868e96", cursor: "help", marginLeft: 2 }}
                >
                  {NOT_TRAINED_MARK}
                </span>
              )}
              {/* The English term stays under the Vietnamese one: it is what
                  radiologists write in reports, and what the reference card
                  and the literature call it. */}
              {lang === "vi" && CONDITIONS[c] && (
                <div
                  style={{ fontSize: "0.68rem", fontWeight: 400, color: "#868e96" }}
                >
                  {CONDITIONS[c].en}
                </div>
              )}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {levels.map((level) => {
          const row = byLevel.get(level)!;
          // Any cell's bbox works for jump; take the first present one.
          const bbox = [...row.values()].find((i) => i.bbox)?.bbox ?? null;
          return (
            <tr
              key={level}
              onClick={() => bbox && onJump(bbox[0])}
              style={{ cursor: bbox ? "pointer" : "default" }}
              title={bbox ? t("Jump to this disc") : undefined}
            >
              <td
                style={{
                  padding: "4px 8px",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  position: "sticky",
                  left: 0,
                  background: "#fff",
                  zIndex: 1,
                }}
              >
                {level}
              </td>
              {conditions.map((c) => {
                const item = row.get(c);
                const low = item != null && item.score < LOW_CONFIDENCE;
                // The cell's own value is unioned in last: a stored severity
                // outside the condition's scale must still display and stay
                // selected rather than silently become a neighbouring value.
                const cellOptions =
                  item && !(optionsByCondition.get(c) ?? []).includes(item.severity)
                    ? [...(optionsByCondition.get(c) ?? []), item.severity]
                    : optionsByCondition.get(c) ?? [];
                return (
                  <td
                    key={c}
                    title={
                      item ? t("confidence {p}%", { p: (item.score * 100).toFixed(0) }) : undefined
                    }
                    style={{
                      padding: "4px 8px",
                      textAlign: "center",
                      background: item ? severityColor(item.severity) : "#eee",
                      border: "1px solid #fff",
                    }}
                  >
                    {item ? (
                      <span
                        style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                      >
                        {onEditSeverity ? (
                          <select
                            value={item.severity}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) =>
                              onEditSeverity(level, c, e.target.value)
                            }
                            style={{
                              font: "inherit",
                              background: "transparent",
                              border: "none",
                            }}
                          >
                            {cellOptions.map((s) => (
                              <option key={s} value={s}>
                                {outOfScale(c, s)
                                  ? `⚠ ${s} (${t("not on this scale")})`
                                  : severityLabel(c, s, lang)}
                              </option>
                            ))}
                          </select>
                        ) : (
                          severityLabel(c, item.severity, lang)
                        )}
                        {low && (
                          <span
                            title={t("Low confidence ({p}%) — review", { p: (item.score * 100).toFixed(0) })}
                            style={{ color: "#c60", cursor: "help" }}
                          >
                            ⚠
                          </span>
                        )}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
    {more.right && (
      <div
        aria-hidden
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 10,
          width: 40,
          pointerEvents: "none",
          background: "linear-gradient(to right, rgba(255,255,255,0), #fff)",
        }}
      />
    )}
    </div>
    {hasUntrainedColumn && (
      <p
        style={{
          margin: "8px 0 0",
          fontSize: "0.72rem",
          lineHeight: 1.5,
          color: "#868e96",
        }}
      >
        {NOT_TRAINED_MARK}{" "}
        {t("Graded by the vendored upstream SpineNet. Corrections to these columns are saved with the study and included in the export, but the re-training loop does not use them — it re-trains only Canal, L. foraminal and R. foraminal, the three heads of the app's own model.")}
      </p>
    )}
    </>
  );
}
