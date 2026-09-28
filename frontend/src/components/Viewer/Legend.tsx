import type { LegendEntry } from "./CornerstoneViewport";
import { Swatch } from "./LabelPicker";
import { useStructureName } from "../../lib/labels";

interface Props {
  entries: LegendEntry[];
  /** When set, the legend doubles as the brush's structure picker. */
  onSelect?: (id: number) => void;
  /** Structure the brush currently paints (highlighted). */
  activeId?: number | null;
}

/**
 * Colour-swatch legend mapping each mask colour to its anatomical structure.
 *
 * While the mask is being edited the same rows become the picker: the doctor
 * reads a colour off the image and clicks it here, instead of translating it
 * into a name and hunting for that name in a separate dropdown.
 */
export default function Legend({ entries, onSelect, activeId }: Props) {
  const structureName = useStructureName();
  if (entries.length === 0) return null;
  return (
    <div
      className="grid grid-cols-2 gap-x-3.5 gap-y-[3px] text-[0.78rem]"
      role={onSelect ? "listbox" : undefined}
      aria-label={onSelect ? "Structure to paint" : undefined}
    >
      {entries.map((e) => {
        const active = onSelect != null && e.id === activeId;
        const content = (
          <>
            <Swatch color={e.color} size={11} />
            <span className="truncate">{structureName(e.name)}</span>
          </>
        );
        return onSelect ? (
          <button
            key={e.id}
            type="button"
            role="option"
            aria-selected={active}
            data-testid={`legend-option-${e.id}`}
            onClick={() => onSelect(e.id)}
            className={
              "flex min-w-0 items-center gap-1.5 rounded px-1 py-0.5 text-left transition hover:bg-teal-50 " +
              (active
                ? "bg-teal-50 font-semibold text-teal-800 ring-1 ring-teal-400"
                : "text-slate-700")
            }
          >
            {content}
          </button>
        ) : (
          <div
            key={e.id}
            className="flex min-w-0 items-center gap-1.5 px-1 py-0.5 text-slate-700"
          >
            {content}
          </div>
        );
      })}
    </div>
  );
}
