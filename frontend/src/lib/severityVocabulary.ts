/**
 * Which severity values each of the 11 grading conditions can actually take,
 * and which of them a doctor's correction can still reach the model through.
 *
 * ## Why this table exists
 *
 * The grade table used to offer one flat option list — the union of every
 * severity value seen anywhere in the study — in every cell. That let
 * "Upper endplate defect" (only ever Absent/Present) be set to "Moderate",
 * which is not a value its head can produce. Such a correction is saved and
 * exported, but `backend/app/feedback/build_dataset.py` drops it as an unknown
 * severity, silently and long after the doctor has moved on. One such value is
 * already in the live database (`right_foraminal: Moderate -> Absent`).
 *
 * ## Where the truth lives, and how this stays honest
 *
 * The backend is the source of truth, in two places:
 *   - `backend/app/inference/grading.py::_SEVERITY_BY_CLASS` — the app's own
 *     fine-tuned CBAM model: Normal/Mild · Moderate · Severe.
 *   - `backend/app/inference/spinenet_grading.py::_SPINENET_COLUMNS` — the
 *     vendored upstream SpineNet heads, each with its own label function
 *     (`_grade_label`, `_spondylolisthesis_label`, `_present_absent`) and a
 *     head width in `backend/spinenet/models/grading.py` (pfirrmann 5,
 *     disc_narrowing 4, spondylolisthesis 3, the rest binary).
 *
 * Nothing serves those vocabularies to the frontend today, so this file
 * mirrors them — which means the two *can* drift. Two things bound the damage:
 *
 *   1. A condition this table does not know gets no invented scale: its
 *      options fall back to the values the study itself holds for it, so a
 *      condition the backend adds is still editable, just not guessed at.
 *   2. A *known* condition offers exactly its declared scale — and the caller
 *      unions in the one value the cell currently holds. So a stored value
 *      outside the scale (a legacy correction, a renamed label) still displays
 *      and stays selected in the cell that has it, without being offered in
 *      the cells that do not.
 *
 * The drift-proof fix is for the backend to serve this table (one small
 * read-only endpoint derived from `_SPINENET_COLUMNS` + `_SEVERITY_BY_CLASS`,
 * fetched here and used in place of `CONDITION_SEVERITIES`). That is a backend
 * change and is deliberately not made here.
 */

/** The app's fine-tuned CBAM model's 3-class scale. */
export const CBAM_SEVERITIES = ["Normal/Mild", "Moderate", "Severe"];

/** `_present_absent` in `spinenet_grading.py`. */
const PRESENT_ABSENT = ["Absent", "Present"];

/**
 * `_spondylolisthesis_label`: Roman numerals, deliberately distinct from the
 * Arabic "Grade N" that Pfirrmann and disc narrowing use.
 */
const SPONDYLOLISTHESIS = ["None", "Grade I", "Grade II"];

/** `_grade_label` over a head of `n` classes, shifted +1 → "Grade 1".."Grade n". */
function gradeScale(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `Grade ${i + 1}`);
}

/**
 * condition -> the values that condition's head can produce, in scale order.
 *
 * A condition missing from this map falls back to whatever the study shows for
 * it, so an entirely new condition is never given a wrong option list.
 */
export const CONDITION_SEVERITIES: Record<string, string[]> = {
  // Fine-tuned CBAM model (app/inference/grading.py).
  canal_stenosis: CBAM_SEVERITIES,
  left_foraminal: CBAM_SEVERITIES,
  right_foraminal: CBAM_SEVERITIES,
  // Upstream SpineNet (app/inference/spinenet_grading.py).
  pfirrmann: gradeScale(5),
  disc_narrowing: gradeScale(4),
  spondylolisthesis: SPONDYLOLISTHESIS,
  upper_endplate_defect: PRESENT_ABSENT,
  lower_endplate_defect: PRESENT_ABSENT,
  upper_marrow: PRESENT_ABSENT,
  lower_marrow: PRESENT_ABSENT,
  disc_herniation: PRESENT_ABSENT,
};

/**
 * The three conditions a correction can still reach the model through.
 *
 * `backend/app/feedback/build_dataset.py` maps a corrected condition onto one
 * of the fine-tuned model's three heads. A correction to any of the other
 * eight is logged, sealed into a batch and exported — but skipped when the
 * training set is built, because those grades come from the vendored upstream
 * SpineNet, which this loop does not re-train. `/admin` already marks those
 * rows "not re-trained"; {@link isTrainableCondition} is how the viewer says
 * the same thing.
 */
const TRAINABLE_CONDITIONS = new Set([
  "canal_stenosis",
  "left_foraminal",
  "right_foraminal",
]);

/** Whether a correction to this condition feeds re-training (see above). */
export function isTrainableCondition(condition: string): boolean {
  return TRAINABLE_CONDITIONS.has(condition);
}

/**
 * The severity options to offer for one condition, in scale order.
 *
 * For a condition in {@link CONDITION_SEVERITIES} this is exactly its declared
 * scale — deliberately *not* unioned with what the study shows, so one stale
 * out-of-scale value on one disc does not become offerable on every other
 * disc of the same column (that union is what let "Moderate" be set on an
 * Absent/Present condition in the first place). The caller is responsible for
 * keeping a cell's own current value visible; see `GradeTable`.
 *
 * @param condition   the grading condition key, e.g. "upper_endplate_defect".
 * @param observed    every severity this study's grading holds for that
 *                    condition. Used only when the condition is unknown here,
 *                    so a condition the backend adds is still editable.
 */
export function severityOptions(
  condition: string,
  observed: Iterable<string>,
): string[] {
  const declared = CONDITION_SEVERITIES[condition];
  if (declared) return declared;
  return [...new Set(observed)]
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}
