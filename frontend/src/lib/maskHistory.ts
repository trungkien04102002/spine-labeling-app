import { utilities } from "@cornerstonejs/core";

const { DefaultHistoryMemo } = utilities.HistoryMemo;

/**
 * Undo/redo for mask painting, backed by Cornerstone's global
 * `DefaultHistoryMemo` ring buffer.
 *
 * The brush and the circle/rectangle scissors commit one RLE memo per stroke
 * (via `LabelmapBaseTool.createMemo` / `doneEditMemo`), so one stroke is one
 * undo step and costs a sparse diff rather than a labelmap copy.
 *
 * This module is the only place the app touches that global. `PaintFillTool`
 * is deliberately not enabled: it writes voxels directly and records no memo,
 * so its edits could not be undone.
 */

/** Strokes kept undoable. 50 is Cornerstone's own default ring size. */
export const MASK_HISTORY_DEPTH = 50;

/**
 * Drop every recorded stroke. Required whenever a new labelmap is loaded: a
 * memo writes back into the voxel manager it was recorded against, so replaying
 * it after a reload would throw or paint into the wrong volume.
 *
 * Assigning `size` is what clears it (the setter re-allocates the ring buffer);
 * there is no `clear()`.
 */
export function resetMaskHistory(): void {
  DefaultHistoryMemo.size = MASK_HISTORY_DEPTH;
}

/**
 * How many steps are currently undoable.
 *
 * A gesture earns a step on the page's Undo timeline only if it deepened this
 * history, which distinguishes a recorded edit from voxels written outside it.
 *
 * `undoAvailable` is private in Cornerstone's typings but a plain field at
 * runtime; `canUndo` is the public fallback, degrading to "at least one step".
 */
export function maskHistoryDepth(): number {
  const depth = (DefaultHistoryMemo as unknown as { undoAvailable?: unknown })
    .undoAvailable;
  if (typeof depth === "number") return depth;
  return DefaultHistoryMemo.canUndo ? 1 : 0;
}

export function canUndoMaskEdit(): boolean {
  return DefaultHistoryMemo.canUndo;
}

export function canRedoMaskEdit(): boolean {
  return DefaultHistoryMemo.canRedo;
}

/** Undo one stroke. Returns false when the history is empty. */
export function undoMaskEdit(): boolean {
  if (!DefaultHistoryMemo.canUndo) return false;
  DefaultHistoryMemo.undo();
  return true;
}

/** Redo one undone stroke. Returns false when there is nothing ahead. */
export function redoMaskEdit(): boolean {
  if (!DefaultHistoryMemo.canRedo) return false;
  DefaultHistoryMemo.redo();
  return true;
}
