import { useEffect, useRef, useState } from "react";
import type { LegendEntry } from "./CornerstoneViewport";
import { swatchColor, useStructureName } from "../../lib/labels";
import { useT } from "../../lib/i18n";

/** The colour square shown next to a structure's name. */
export function Swatch({
  color,
  size = 12,
}: {
  color: [number, number, number] | null;
  size?: number;
}) {
  return (
    <span
      aria-hidden
      className="inline-block shrink-0 rounded-[3px] border border-black/15"
      style={{
        width: size,
        height: size,
        background: color ? swatchColor(color) : "repeating-linear-gradient(45deg,#e2e8f0,#e2e8f0 3px,#f8fafc 3px,#f8fafc 6px)",
      }}
    />
  );
}

interface Props {
  /** Structures with the colour they are actually drawn in (from the LUT). */
  entries: LegendEntry[];
  /** Selected structure id, or null when the doctor has not chosen one yet. */
  value: number | null;
  onChange: (id: number) => void;
  disabled?: boolean;
  /** Open the list on mount (used when edit mode starts with no choice made). */
  autoOpen?: boolean;
}

/**
 * Structure picker for the brush: colour and name in one control.
 *
 * A native <select> cannot carry a colour swatch on every platform, and the
 * colour is the only thing that connects a name to the shape on screen -- so
 * this is a small custom listbox instead. The swatches are the labelmap's own
 * rendered colours, passed in from the viewport's LUT, never a palette of our
 * own: a picker that showed a different green from the canvas would be worse
 * than no colour at all.
 */
export default function LabelPicker({
  entries,
  value,
  onChange,
  disabled,
  autoOpen,
}: Props) {
  const structureName = useStructureName();
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoOpen) setOpen(true);
  }, [autoOpen]);

  useEffect(() => {
    if (!open) return;
    function onDocDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const selected = entries.find((e) => e.id === value) ?? null;

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        data-testid="label-picker-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={
          "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 " +
          (selected
            ? "border-slate-300 bg-white text-slate-700 hover:border-teal-400"
            : "border-amber-400 bg-amber-50 text-amber-800 hover:border-amber-500")
        }
      >
        <Swatch color={selected ? selected.color : null} />
        <span data-testid="label-picker-value">
          {selected ? structureName(selected.name) : t("Choose a structure…")}
        </span>
        <span aria-hidden className="text-[9px] opacity-60">
          ▼
        </span>
      </button>

      {open && (
        <ul
          role="listbox"
          data-testid="label-picker-list"
          aria-label="Structure to paint"
          className="absolute left-0 z-20 mt-1 max-h-72 w-60 overflow-y-auto rounded-md border border-slate-200 bg-white py-1 text-left shadow-lg"
        >
          {entries.map((e) => (
            <li key={e.id} role="option" aria-selected={e.id === value}>
              <button
                type="button"
                data-testid={`label-option-${e.id}`}
                onClick={() => {
                  onChange(e.id);
                  setOpen(false);
                }}
                className={
                  "flex w-full items-center gap-2 px-2.5 py-1 text-xs transition hover:bg-teal-50 " +
                  (e.id === value
                    ? "bg-teal-50 font-semibold text-teal-800"
                    : "text-slate-700")
                }
              >
                <Swatch color={e.color} />
                {structureName(e.name)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
