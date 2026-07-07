import type { GradingItem } from "../../lib/api";

const LEVEL_ORDER = ["L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1"];
const CONDITIONS = [
  { key: "canal_stenosis", label: "Canal" },
  { key: "left_foraminal", label: "L. foraminal" },
  { key: "right_foraminal", label: "R. foraminal" },
];

/** Background color for a severity label. */
function severityColor(severity: string): string {
  if (severity === "Severe") return "#f8d0d0";
  if (severity === "Moderate") return "#fce7c4";
  return "#d8f0d8"; // Normal/Mild
}

interface Props {
  grading: GradingItem[];
  /** Called with a slice index when a level row is clicked (jump-to-disc). */
  onJump: (slice: number) => void;
}

/**
 * Per-disc abnormality grades: one row per lumbar level, one cell per condition
 * (color-coded by severity). Clicking a row scrolls the viewer to that disc.
 */
export default function GradeTable({ grading, onJump }: Props) {
  // Index items by level+condition for O(1) cell lookup.
  const byLevel = new Map<string, Map<string, GradingItem>>();
  for (const item of grading) {
    if (!byLevel.has(item.level)) byLevel.set(item.level, new Map());
    byLevel.get(item.level)!.set(item.condition, item);
  }

  const levels = LEVEL_ORDER.filter((l) => byLevel.has(l));

  return (
    <table
      style={{
        borderCollapse: "collapse",
        fontSize: "0.85rem",
        width: "100%",
        maxWidth: 520,
      }}
    >
      <thead>
        <tr>
          <th style={{ textAlign: "left", padding: "4px 8px" }}>Level</th>
          {CONDITIONS.map((c) => (
            <th key={c.key} style={{ padding: "4px 8px" }}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {levels.map((level) => {
          const row = byLevel.get(level)!;
          const bbox = row.get("canal_stenosis")?.bbox ?? null;
          return (
            <tr
              key={level}
              onClick={() => bbox && onJump(bbox[0])}
              style={{ cursor: bbox ? "pointer" : "default" }}
              title={bbox ? "Jump to this disc" : undefined}
            >
              <td style={{ padding: "4px 8px", fontWeight: 600 }}>{level}</td>
              {CONDITIONS.map((c) => {
                const item = row.get(c.key);
                return (
                  <td
                    key={c.key}
                    style={{
                      padding: "4px 8px",
                      textAlign: "center",
                      background: item ? severityColor(item.severity) : "#eee",
                      border: "1px solid #fff",
                    }}
                  >
                    {item ? (
                      <>
                        {item.severity}
                        <br />
                        <span style={{ color: "#666", fontSize: "0.75rem" }}>
                          {(item.score * 100).toFixed(0)}%
                        </span>
                      </>
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
  );
}
