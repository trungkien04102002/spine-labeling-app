import type { LegendEntry } from "./CornerstoneViewport";

/** Prettify a TotalSpineSeg label name, e.g. "vertebrae_L1" -> "Vertebra L1". */
function prettyName(name: string): string {
  if (name.startsWith("vertebrae_")) return `Vertebra ${name.slice(10)}`;
  if (name.startsWith("disc_")) return `Disc ${name.slice(5).replace(/_/g, "-")}`;
  return name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Color-swatch legend mapping each mask color to its anatomical structure. */
export default function Legend({ entries }: { entries: LegendEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
        gap: "3px 14px",
        fontSize: "0.78rem",
      }}
    >
      {entries.map((e) => (
        <div
          key={e.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            whiteSpace: "nowrap",
          }}
        >
          <span
            style={{
              display: "inline-block",
              width: 11,
              height: 11,
              borderRadius: 2,
              background: `rgb(${e.color[0]},${e.color[1]},${e.color[2]})`,
              flexShrink: 0,
            }}
          />
          {prettyName(e.name)}
        </div>
      ))}
    </div>
  );
}
