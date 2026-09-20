import { utilities } from "@cornerstonejs/core";

const { DefaultHistoryMemo } = utilities.HistoryMemo;

/**
 * Undo/redo for mask painting.
 *
 * Cornerstone's brush already records every stroke: while a stroke is drawn the
 * writes go through an RLE "memo" that keeps only the *previous* value of each
 * voxel it overwrites, and on mouse-up the tool commits that memo onto a global
 * ring buffer (`DefaultHistoryMemo`). So one stroke is exactly one undo step,
 * and a step costs a sparse run-length diff of the painted area -- kilobytes --
 * rather than a copy of the labelmap (a 320x320x20 mask is ~2 MB per copy).
 *
 * This module is the only place the app touches that global, so the rules for
 * using it safely stay in one file. The brush and the circle/rectangle scissors
 * push memos here (all three go through `LabelmapBaseTool.createMemo` /
 * `doneEditMemo`); the annotation tools that would also use it are not enabled
 * in this viewer. `PaintFillTool` deliberately is not enabled either -- it
 * writes voxels straight through the voxel manager and records nothing, so an
 * edit made with it could not be undone.
 */

/** Strokes kept undoable. 50 is Cornerstone's own default ring size. */
export const MASK_HISTORY_DEPTH = 50;

/**
 * Drop every recorded stroke. Required whenever a new labelmap is loaded (new
 * study, or a series switch that rebuilds the derived images): a stored memo
 * writes back into the voxel manager it was recorded against, and replaying one
 * onto a labelmap that no longer exists would either throw or, worse, paint
 * into the wrong volume.
 *
 * Assigning `size` is what clears it -- the setter re-allocates the ring buffer
 * and resets the cursor. There is no `clear()`.
 */
export function resetMaskHistory(): void {
  DefaultHistoryMemo.size = MASK_HISTORY_DEPTH;
}

/**
 * How many steps are currently undoable.
 *
 * This is the app's proof that an edit is reversible: a gesture only earns a
 * step on the page's Undo timeline if it actually deepened this history. Asking
 * the tool "did you paint?" cannot tell the difference between a tool that
 * recorded a memo and one that wrote voxels behind the history's back -- this
 * can.
 *
 * `undoAvailable` is private in Cornerstone's typings but a plain field at
 * runtime; the boolean `canUndo` is the public fallback if that ever changes,
 * which degrades to "at least one step" rather than to nothing.
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
