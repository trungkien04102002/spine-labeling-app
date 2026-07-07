import type { GradingItem } from "../../lib/api";

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
const CONDITION_ORDER = [
  "canal_stenosis",
  "left_foraminal",
  "right_foraminal",
];
const CONDITION_LABELS: Record<string, string> = {
  canal_stenosis: "Canal",
  left_foraminal: "L. foraminal",
  right_foraminal: "R. foraminal",
};
const SEVERITIES = ["Normal/Mild", "Moderate", "Severe"];
const LOW_CONFIDENCE = 0.5;

/** Prettify an unknown condition key, e.g. "disc_herniation" -> "Disc herniation". */
function conditionLabel(key: string): string {
  return (
    CONDITION_LABELS[key] ??
    key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
}

/** Background color for a severity label (neutral for values we don't know). */
function severityColor(severity: string): string {
  if (severity === "Severe") return "#f8d0d0";
  if (severity === "Moderate") return "#fce7c4";
  if (severity === "Normal/Mild") return "#d8f0d8";
  return "#eef0f4"; // unknown severity scale (e.g. a Pfirrmann grade)
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
export default function GradeTable({ grading, onJump, onEditSeverity }: Props) {
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
  // Include every severity the model actually used, so the dropdown can
  // represent scales beyond Normal/Mild/Moderate/Severe.
  const severityOptions = ordered(
    [...new Set([...SEVERITIES, ...grading.map((g) => g.severity)])],
    SEVERITIES,
  );

  return (
    <div style={{ overflowX: "auto" }}>
    <table
      style={{
        borderCollapse: "collapse",
        fontSize: "0.85rem",
        width: "100%",
      }}
    >
      <thead>
        <tr>
          <th style={{ textAlign: "left", padding: "4px 8px" }}>Level</th>
          {conditions.map((c) => (
            <th key={c} style={{ padding: "4px 8px" }}>
              {conditionLabel(c)}
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
              title={bbox ? "Jump to this disc" : undefined}
            >
              <td style={{ padding: "4px 8px", fontWeight: 600 }}>{level}</td>
              {conditions.map((c) => {
                const item = row.get(c);
                const low = item != null && item.score < LOW_CONFIDENCE;
                return (
                  <td
                    key={c}
                    title={
                      item ? `confidence ${(item.score * 100).toFixed(0)}%` : undefined
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
                            {severityOptions.map((s) => (
                              <option key={s} value={s}>
                                {s}
                              </option>
                            ))}
                          </select>
                        ) : (
                          item.severity
                        )}
                        {low && (
                          <span
                            title={`Low confidence (${(item.score * 100).toFixed(0)}%) — review`}
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
  );
}
