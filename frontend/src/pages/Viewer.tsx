import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CornerstoneViewport, {
  type LegendEntry,
  type MaskEditApi,
} from "../components/Viewer/CornerstoneViewport";
import GradeTable from "../components/Viewer/GradeTable";
import ReferenceBPanel from "../components/Viewer/ReferenceBPanel";
import FindingsSummary, { MyEdits } from "../components/Viewer/FindingsSummary";
import ModelBadge from "../components/Viewer/ModelBadge";
import LabelReference from "../components/Viewer/LabelReference";
import Legend from "../components/Viewer/Legend";
import { useHistory } from "../lib/history";
import {
  API_BASE_URL,
  exportUrl,
  fullGradingCsvUrl,
  fullGradingJsonUrl,
  getAnnotation,
  getCorrections,
  getFullGrading,
  getSeries,
  getStudyDetail,
  getJob,
  getReferenceBVisibility,
  startFullGrading,
  saveAnnotation,
  saveMask,
  setActiveSeries,
  submitCorrections,
  type CorrectionQueue,
  type JobOut,
  type FullGradingResult,
  type InferResult,
  type SeriesOut,
  type StudyDetail,
} from "../lib/api";
import { LangToggle, useT } from "../lib/i18n";
import { displayStudyId, useRoom } from "../lib/room";

/**
 * Translucent metadata overlay pinned to a corner of the image, the way a PACS
 * workstation annotates the view. Patient/study identity sits top-left;
 * acquisition parameters (DICOM only) can be toggled open.
 */
function InfoOverlay({ detail }: { detail: StudyDetail }) {
  const { t } = useT();
  const [showTags, setShowTags] = useState(false);
  const dims = detail.dimensions;
  const sp = detail.spacing_mm;
  const tagEntries = Object.entries(detail.dicom_tags);

  return (
    <div
      style={{
        position: "absolute",
        top: 8,
        left: 8,
        zIndex: 2,
        color: "#d8f0ff",
        font: "11px/1.4 monospace",
        textShadow: "0 0 3px #000",
        pointerEvents: "none",
        maxWidth: "45%",
      }}
    >
      <div style={{ fontWeight: 700 }}>{detail.patient_name}</div>
      <div>ID {detail.patient_id} · {detail.id}</div>
      <div>
        {detail.modality === "MR" ? "MRI" : detail.modality} · {new Date(detail.created_at).toLocaleDateString()}
      </div>
      {dims && (
        <div>
          {dims[0]}×{dims[1]}×{dims[2]} · {detail.num_slices} sl
        </div>
      )}
      {sp && (
        <div>
          {sp[0]}×{sp[1]}×{sp[2]} mm
        </div>
      )}
      <div>seg: {detail.has_mask ? "on" : "—"}</div>
      {tagEntries.length > 0 && (
        <div style={{ pointerEvents: "auto", marginTop: 4 }}>
          <button
            onClick={() => setShowTags((v) => !v)}
            style={{
              font: "10px monospace",
              background: "rgba(0,0,0,0.4)",
              color: "#d8f0ff",
              border: "1px solid #567",
              borderRadius: 3,
              cursor: "pointer",
            }}
          >
            {showTags ? `▾ ${t("acquisition")}` : `▸ ${t("acquisition")}`}
          </button>
          {showTags &&
            tagEntries.map(([k, v]) => (
              <div key={k}>
                {k}: {v}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

// What each predicted grade means, shown in the "About this tool" panel so a
// reader knows what the model outputs (wording follows the Oxford SpineNet demo
// + standard lumbar-MRI radiology). Which model grades which column is
// operator information and is deliberately not shown to the doctor.
// `scale` spells out the exact values, and must stay in step with
// `lib/severityVocabulary.ts` — that is what the grade table's dropdowns offer.
const PREDICTION_GUIDE: { name: string; scale: string; meaning: string }[] = [
  { name: "Pfirrmann", scale: "Grade 1–5", meaning: "Disc degeneration, from healthy (1) to severely degenerated (5)." },
  { name: "Disc narrowing", scale: "Grade 1–4", meaning: "Loss of intervertebral disc height." },
  { name: "Central canal stenosis", scale: "Normal/Mild · Moderate · Severe", meaning: "Narrowing of the central spinal canal." },
  { name: "Foraminal stenosis (L/R)", scale: "Normal/Mild · Moderate · Severe", meaning: "Narrowing of the left/right nerve-exit foramen." },
  { name: "Spondylolisthesis", scale: "None · Grade I · Grade II+", meaning: "Forward slippage of one vertebra over another." },
  { name: "Endplate defects (upper/lower)", scale: "Absent / Present", meaning: "Damage to the vertebral endplate." },
  { name: "Marrow changes (upper/lower)", scale: "Absent / Present", meaning: "Modic vertebral bone-marrow signal changes." },
  { name: "Disc herniation", scale: "Absent / Present", meaning: "Protrusion/extrusion of disc material." },
];

// The three columns the project's own model owns. Their absence is the visible
// symptom of an upstream failure (no lumbar disc labels in the mask), and it
// looks exactly like a normal result unless it is called out.
const CBAM_CONDITIONS = ["canal_stenosis", "left_foraminal", "right_foraminal"];

function missingCbamColumns(grading: { condition: string }[]): boolean {
  if (grading.length === 0) return false;
  const present = new Set(grading.map((g) => g.condition));
  return CBAM_CONDITIONS.every((c) => !present.has(c));
}

/** One step on the shared undo timeline: a grade change or one brush stroke. */
type EditKind = "grade" | "mask";

/** "7m 12s" — mm:ss reads as a duration; a raw second count does not. */
function formatElapsed(seconds: number): string {
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  return minutes > 0 ? `${minutes}m ${total % 60}s` : `${total}s`;
}

const PLANE_LABEL: Record<string, string> = {
  sagittal: "Sagittal",
  axial: "Axial",
  coronal: "Coronal",
  unknown: "Series",
};

/**
 * Series picker: one tab per acquisition in the study (sagittal T1, sagittal
 * T2, axial T2 ...), so a doctor can read across every plane the way they do
 * on a PACS.
 *
 * The models read ONE acquisition, so the tab the AI actually ran on is marked
 * and the rest are labelled view-only. Stating that plainly is deliberate: a
 * multi-plane picker would otherwise imply the model fuses all views, which it
 * does not (yet).
 */
function SeriesPicker({
  series,
  busy,
  onSelect,
}: {
  series: SeriesOut[];
  busy: boolean;
  onSelect: (id: number) => void;
}) {
  const { t } = useT();
  if (series.length < 2) return null;
  const analyzed = series.find((s) => s.analyzed_by_ai);
  return (
    <div className="border-b border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-semibold text-slate-500">
          {t("Series")}
        </span>
        {series.map((s) => (
          <button
            key={s.id}
            type="button"
            disabled={busy || s.is_active}
            onClick={() => onSelect(s.id)}
            title={s.description ?? s.series_uid}
            className={
              "rounded-md border px-2.5 py-1 text-xs font-medium transition " +
              (s.is_active
                ? "border-teal-500 bg-teal-600 text-white shadow-sm"
                : "border-slate-300 bg-white text-slate-600 hover:border-teal-400 hover:text-teal-700 disabled:opacity-50")
            }
          >
            {t(PLANE_LABEL[s.orientation] ?? "Series")}
            {/* Spaces are real text, not just margins: they keep the button's
                accessible name readable ("Sagittal T2 (15)"). */}
            {s.description ? (
              <span className="font-normal opacity-80"> {s.description}</span>
            ) : null}
            {s.num_slices ? (
              <span className="font-normal opacity-60"> ({s.num_slices})</span>
            ) : null}
          </button>
        ))}
        {busy ? (
          <span className="ml-1 text-xs text-slate-500">{t("Loading…")}</span>
        ) : null}
      </div>
      <p className="mt-1.5 text-[11px] leading-snug text-slate-500">
        {analyzed ? (
          <>
            {/* The badge that used to mark this series was removed, so name the
                series here instead: which sequence produced the grades is not
                something the doctor should have to infer. */}
            {t("The grades come from the")}{" "}
            <strong>
              {t(PLANE_LABEL[analyzed.orientation] ?? "Sagittal")}
              {analyzed.description ? ` ${analyzed.description}` : ""}
            </strong>{" "}
            {t("series. Browse any series freely — switching does not change the grades.")}
          </>
        ) : (
          <>
            {t("Browse any plane freely. “Run AI grading” always grades the sagittal series, whichever one you are viewing.")}
          </>
        )}
      </p>
    </div>
  );
}

export default function Viewer() {
  const { t } = useT();
  const { room, leave } = useRoom();
  const { studyId } = useParams<{ studyId: string }>();
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [series, setSeries] = useState<SeriesOut[]>([]);
  // The viewport waits for the series list, so it mounts once on the right
  // series instead of once on "none" and again a moment later.
  const [seriesLoaded, setSeriesLoaded] = useState(false);
  const [seriesBusy, setSeriesBusy] = useState(false);
  // Grade edits flow through an undo/redo history; `result` is its cursor.
  const gradeHistory = useHistory<InferResult | null>(null);
  const result = gradeHistory.state;
  const [targetSlice, setTargetSlice] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  // The segmentation's labels while a run is still grading (null otherwise).
  const [previewLabels, setPreviewLabels] = useState<Record<string, string> | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [maskDirty, setMaskDirty] = useState(false);
  const [legend, setLegend] = useState<LegendEntry[]>([]);
  const editApiRef = useRef<MaskEditApi | null>(null);
  // Mask editing is owned here, not inside the viewport, so the Structures
  // panel can act as the brush's picker.
  const [editMode, setEditMode] = useState(false);
  // No default structure: whatever sorts first (spinal_cord, a 2-pixel-wide
  // cord) is nobody's intended first brush. The doctor chooses, and until they
  // do the brush stays off -- see CornerstoneViewport.
  const [activeLabel, setActiveLabel] = useState<number | null>(null);
  // Grades and brush strokes have separate undo machinery (an immutable value
  // stack; Cornerstone's per-stroke voxel diffs), but a doctor should not have
  // to know that. This records only WHICH of the two each edit was, in order,
  // so one Undo button walks back through both in the order they happened.
  const [undoKinds, setUndoKinds] = useState<EditKind[]>([]);
  const [redoKinds, setRedoKinds] = useState<EditKind[]>([]);

  // "Run AI grading" produces the full 11-label grading (SpineNet + CBAM) AND persists a
  // v0 annotation, so the editable `result` above IS the 11-label table. We keep
  // `fullResult` only for the extras the annotation doesn't carry: the labelled
  // slice image and the CSV/JSON download URLs.
  const [fullResult, setFullResult] = useState<FullGradingResult | null>(null);
  const [corrections, setCorrections] = useState<CorrectionQueue | null>(null);
  const [submittingCorrections, setSubmittingCorrections] = useState(false);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [job, setJob] = useState<JobOut | null>(null);
  // Bumped when a grading run finishes, so the viewport reloads and shows the
  // new segmentation without the doctor pressing F5.
  // Bumped when a grading run writes a new mask: the viewer swaps the overlay
  // in place instead of reloading the picture.
  const [maskRun, setMaskRun] = useState(0);
  // A level (or one finding) picked in the summary, for the table to scroll
  // to and pulse.
  const [tableHighlight, setTableHighlight] = useState<
    { level: string; condition?: string; nonce: number } | null
  >(null);
  // Whether clinicians are shown model B (an /admin switch): decides whether
  // the guide above the results talks about one model or two.
  const [modelBShown, setModelBShown] = useState(false);
  useEffect(() => {
    getReferenceBVisibility()
      .then((v) => setModelBShown(v.visible && v.installed))
      .catch(() => setModelBShown(false));
  }, []);

  // The correction queue spans every study, so it loads once, not per-study.
  useEffect(() => {
    getCorrections()
      .then(setCorrections)
      .catch(() => setCorrections(null));
  }, []);

  useEffect(() => {
    if (!studyId) return;
    getStudyDetail(studyId)
      .then(setDetail)
      .catch(() => setDetail(null));
    setSeriesLoaded(false);
    getSeries(studyId)
      .then(setSeries)
      .catch(() => setSeries([]))
      .finally(() => setSeriesLoaded(true));
    setUndoKinds([]);
    setRedoKinds([]);
    getAnnotation(studyId)
      .then((r) => {
        gradeHistory.reset(r);
        setDirty(false);
      })
      .catch(() => gradeHistory.reset(null)); // 404 = inference not run yet
    getFullGrading(studyId)
      .then((r) => {
        setFullResult(r);
      })
      .catch(() => setFullResult(null)); // 404 = full grading not run yet
    // gradeHistory identity is stable; only re-run when the study changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId]);

  // Switching series repoints the study's display volume, so the viewer and the
  // header metadata both have to be reloaded.
  async function handleSelectSeries(seriesId: number) {
    if (!studyId) return;
    setSeriesBusy(true);
    try {
      setSeries(await setActiveSeries(studyId, seriesId));
      setDetail(await getStudyDetail(studyId));
    } catch {
      setRunError("Could not switch series.");
    } finally {
      setSeriesBusy(false);
    }
  }

  // Single entry point: run the full 11-label pipeline (segments once, grades
  // with SpineNet + CBAM, persists the mask + a v0 annotation + the labelled
  // slice), then reload the editable annotation, the slice/export extras, and
  // the study detail (so the viewer picks up the fresh mask).
  //
  // Grading takes 8-15 minutes on CPU, so this starts a background job and
  // polls it rather than holding one request open the whole time: a proxy in
  // front of the app would cut a request that long, and a bare spinner gives
  // the doctor no way to tell work from a hang.
  async function handleRunAI() {
    if (!studyId) return;
    setRunning(true);
    setRunError(null);
    setJob(null);
    setEditMode(false);
    try {
      let current = await startFullGrading(studyId);
      setJob(current);

      let segShown = false;
      while (current.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        current = await getJob(current.id);
        setJob(current);
        // Segmentation first, diagnoses after: draw the mask as soon as it
        // exists, while the discs are still being graded.
        if (!segShown && current.segmentation_labels) {
          segShown = true;
          setPreviewLabels(current.segmentation_labels);
          getStudyDetail(studyId).then(setDetail).catch(() => {});
          setMaskRun((n) => n + 1);
        }
      }

      if (current.status === "error") {
        throw new Error(current.error ?? "Grading failed");
      }

      // The job persisted the result; fetch it the same way a reload would.
      setFullResult(await getFullGrading(studyId));
      const ann = await getAnnotation(studyId);
      gradeHistory.reset(ann);
      setUndoKinds([]);
      setRedoKinds([]);
      setDirty(false);
      getStudyDetail(studyId).then(setDetail).catch(() => {});
      getSeries(studyId).then(setSeries).catch(() => {});
      setMaskRun((n) => n + 1);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
      setJob(null);
      setPreviewLabels(null);
    }
  }

  function handleEditSeverity(level: string, condition: string, severity: string) {
    if (!result) return;
    gradeHistory.set({
      ...result,
      grading: result.grading.map((g) =>
        g.level === level && g.condition === condition ? { ...g, severity } : g,
      ),
    });
    setUndoKinds((k) => [...k, "grade"]);
    setRedoKinds([]);
    setDirty(true);
    setSavedNote(null);
  }

  /**
   * Put graded cells back to what model A said -- one, or all of them -- as a
   * single undoable step. Works on edits saved earlier too: the AI's own
   * grades are kept (grade_full.json), so nothing has to be remembered.
   */
  function handleRevertToAI(cells: { level: string; condition: string; severity: string }[]) {
    if (!result || cells.length === 0) return;
    const back = new Map(cells.map((c) => [`${c.level}/${c.condition}`, c.severity]));
    gradeHistory.set({
      ...result,
      grading: result.grading.map((g) => {
        const v = back.get(`${g.level}/${g.condition}`);
        return v === undefined ? g : { ...g, severity: v };
      }),
    });
    setUndoKinds((k) => [...k, "grade"]);
    setRedoKinds([]);
    setDirty(true);
    setSavedNote(null);
  }

  /** One finished brush stroke: one step on the shared undo timeline. */
  function handleMaskStroke() {
    setMaskDirty(true);
    setUndoKinds((k) => [...k, "mask"]);
    setRedoKinds([]);
    setSavedNote(null);
  }

  /**
   * A new labelmap was loaded (study opened, series switched). Cornerstone's
   * stroke history was dropped with it, so drop our mask steps too rather than
   * leave Undo promising to revert strokes that can no longer be replayed.
   */
  function handleMaskHistoryReset() {
    setUndoKinds((k) => k.filter((x) => x !== "mask"));
    setRedoKinds((k) => k.filter((x) => x !== "mask"));
    setMaskDirty(false);
  }

  function applyStep(kind: EditKind, direction: "undo" | "redo"): boolean {
    if (kind === "mask") {
      const api = editApiRef.current;
      if (!api) return false;
      const done = direction === "undo" ? api.undoStroke() : api.redoStroke();
      if (done) setMaskDirty(true);
      return done;
    }
    if (direction === "undo") {
      if (!gradeHistory.canUndo) return false;
      gradeHistory.undo();
    } else {
      if (!gradeHistory.canRedo) return false;
      gradeHistory.redo();
    }
    setDirty(true);
    return true;
  }

  function handleUndo() {
    // Skip past any step that can no longer be replayed (e.g. a stroke that
    // fell off the end of Cornerstone's bounded history) instead of appearing
    // to do nothing.
    const remaining = [...undoKinds];
    while (remaining.length > 0) {
      const kind = remaining.pop() as EditKind;
      if (applyStep(kind, "undo")) {
        setUndoKinds(remaining);
        setRedoKinds((k) => [kind, ...k]);
        setSavedNote(null);
        return;
      }
    }
    setUndoKinds([]);
  }

  function handleRedo() {
    const remaining = [...redoKinds];
    while (remaining.length > 0) {
      const kind = remaining.shift() as EditKind;
      if (applyStep(kind, "redo")) {
        setRedoKinds(remaining);
        setUndoKinds((k) => [...k, kind]);
        setSavedNote(null);
        return;
      }
    }
    setRedoKinds([]);
  }

  // Ctrl/Cmd+Z = undo, Ctrl/Cmd+Shift+Z (or Ctrl+Y) = redo.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      } else if ((key === "z" && e.shiftKey) || key === "y") {
        e.preventDefault();
        handleRedo();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function handleSave() {
    if (!studyId || !result) return;
    setSaving(true);
    try {
      // Persist the edited mask first (if painted), then the corrected grades.
      if (maskDirty && editApiRef.current) {
        const voxels = editApiRef.current.getMaskVolume();
        if (voxels) await saveMask(studyId, voxels);
        setMaskDirty(false);
      }
      await saveAnnotation(studyId, result);
      setDirty(false);
      setSavedNote(t("Saved as a new corrected version."));
      // Saving is what creates correction rows, so the queue just changed.
      void refreshCorrections();
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function refreshCorrections() {
    try {
      setCorrections(await getCorrections());
    } catch {
      // The queue is a side panel; failing to load it must not take down the
      // viewer the doctor is actually here to use.
      setCorrections(null);
    }
  }

  async function handleSubmitCorrections() {
    setSubmittingCorrections(true);
    setSubmitMessage(null);
    try {
      const result = await submitCorrections();
      // Built here rather than shown as sent: the server's sentence embeds
      // the batch id, so it can never match a dictionary entry.
      setSubmitMessage(
        result.submitted === 0
          ? t("No corrections are waiting to be sent.")
          : t(
              "Sent {n} correction(s). Thank you — they are reviewed later and do not change any result right away.",
              { n: result.submitted, id: result.batch_id },
            ),
      );
      await refreshCorrections();
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmittingCorrections(false);
    }
  }

  // "Corrections" means grade corrections in this app (they feed correction_log).
  // Saying that after a mask edit names the wrong thing, so the button reports
  // whichever kind is actually pending.
  const saveLabel = t(
    !dirty && !maskDirty
      ? "Save"
      : dirty && maskDirty
        ? "Save changes"
        : maskDirty
          ? "Save mask"
          : "Save corrections",
  );

  const btn =
    "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed";

  return (
    <div className="min-h-screen">
      {/* Colorful brand header */}
      <header className="bg-gradient-to-r from-teal-600 to-cyan-500 shadow-md">
        <div className="mx-auto flex max-w-7xl 2xl:max-w-[1680px] flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3 text-white">
            <Link
              to="/"
              className="whitespace-nowrap rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium backdrop-blur transition hover:bg-white/25"
            >
              {t("← Worklist")}
            </Link>
            <div className="leading-tight">
              <div className="text-sm font-bold">{t("Study {id}", { id: displayStudyId(studyId ?? "") })}</div>
              <div className="text-xs text-teal-50/90">
                {detail?.patient_name ?? "…"}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          {/* The room and the survey are on this page too: most of a visit is
              spent here, and the survey link was easy to miss on the list. */}
          <span className="hidden items-center gap-2 rounded-lg bg-white/15 px-3 py-1.5 text-xs text-white md:flex">
            <span className="text-teal-50/80">{t("Room")}</span>
            <span className="font-semibold">{room?.name}</span>
            <button
              type="button"
              onClick={leave}
              className="rounded border border-white/40 px-1.5 py-0.5 text-[10px] font-medium hover:bg-white/20"
            >
              {t("Switch")}
            </button>
          </span>
          <Link
            to="/survey"
            title={t("A short survey, about 5 minutes")}
            className="whitespace-nowrap rounded-lg border border-white/60 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/15"
          >
            ★ {t("Rate this software")}
          </Link>
          <LangToggle />
          <button
            onClick={handleRunAI}
            disabled={running || !!detail?.is_picture}
            title={detail?.is_picture ? t("A picture can only be read by model B. Model A needs an MRI series.") : undefined}
            className="whitespace-nowrap rounded-lg bg-white px-4 py-1.5 text-sm font-semibold text-teal-700 shadow-sm transition hover:bg-teal-50 disabled:opacity-60"
          >
            {running ? t("Grading…") : t("✨ Run AI grading")}
          </button>
          </div>
        </div>

        {/* Grading runs for 8-15 minutes on CPU. Showing the current stage and
            elapsed time — rather than a bare spinner or a fake smooth bar —
            is what lets a doctor tell steady progress from a stall. */}
        {running && (
          <div className="border-t border-white/20 bg-teal-700/40 px-4 py-2 sm:px-6">
            <div className="mx-auto flex max-w-7xl 2xl:max-w-[1680px] items-center gap-3">
              <div
                className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/25"
                role="progressbar"
                aria-valuenow={job?.percent ?? 0}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={t("Grading progress")}
              >
                <div
                  className="h-full rounded-full bg-white transition-all duration-500"
                  style={{ width: `${job?.percent ?? 5}%` }}
                />
              </div>
              <span className="whitespace-nowrap text-xs font-medium text-white">
                {t(job?.stage ?? "Starting")}
                {job ? ` · ${formatElapsed(job.elapsed_seconds)}` : ""}
              </span>
            </div>
            <p className="mx-auto mt-1 max-w-7xl 2xl:max-w-[1680px] text-[11px] text-teal-50/80">
              {t("Usually 1–2 minutes. Press it and leave it: you can even leave this page — the run continues on the server and the result is saved.")}
            </p>
          </div>
        )}
      </header>

      <main className="mx-auto flex max-w-7xl 2xl:max-w-[1680px] flex-col gap-5 px-4 py-4 sm:px-6 sm:py-6">
          {/* About this tool — first on the page, collapsed; the button says it opens. */}
          <details className="group rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <summary className="flex cursor-pointer list-none items-center gap-2 text-base font-bold text-slate-800 [&::-webkit-details-marker]:hidden">
              <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
              {t("About this tool")}
              <span className="ml-auto rounded-md border border-teal-300 px-2.5 py-1 text-xs font-semibold text-teal-700 group-open:hidden">
                ▼ {t("Click to read")}
              </span>
              <span className="ml-auto hidden rounded-md border border-slate-300 px-2.5 py-1 text-xs font-semibold text-slate-600 group-open:inline">
                ▲ {t("Collapse")}
              </span>
            </summary>
            <div className="mt-3 space-y-3 text-xs text-slate-600">
              <p>
                {t("This tool automatically reads a lumbar spine MRI and produces radiological grades for each intervertebral disc level (T12–L1 down to L5–S1). Click a level in the table to jump to its slice; you can correct any grade and save it.")}
              </p>
              <div>
                <p className="mb-1 font-semibold text-slate-700">
                  {t("What it predicts")}
                </p>
                <ul className="space-y-1.5">
                  {PREDICTION_GUIDE.map((g) => (
                    <li key={g.name}>
                      <span className="font-medium text-slate-700">
                        {g.name}
                      </span>{" "}
                      <span className="text-slate-400">({g.scale})</span>:{" "}
                      {t(g.meaning)}
                    </li>
                  ))}
                </ul>
              </div>
              <p className="rounded-md bg-amber-50 px-2.5 py-1.5 text-amber-700">
                {t("⚠ Research use only — this is not a diagnostic tool or a medical device.")}
              </p>
            </div>
          </details>

        {/* Top row: the picture, and beside it what is wrong with it. The
            side column is held to the picture's height and scrolls inside
            itself, so it can never leave an empty gap under the image -- a
            clinician took that gap for the end of the page. Everything read
            against the image (grades, feedback, model B) follows full width. */}
        <div
          className={
            "grid gap-5 " +
            (detail?.has_mask ? "lg:grid-cols-[minmax(0,3fr)_minmax(280px,1fr)]" : "")
          }
        >
        <section className="min-w-0">
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <SeriesPicker
              series={series}
              busy={seriesBusy}
              onSelect={handleSelectSeries}
            />
            {studyId && seriesLoaded && (
              <CornerstoneViewport
                studyId={studyId}
                apiBaseUrl={API_BASE_URL}
                seriesKey={series.find((s) => s.is_active)?.id ?? null}
                maskKey={maskRun}
                overlay={detail ? <InfoOverlay detail={detail} /> : null}
                targetSlice={targetSlice}
                segLabels={previewLabels ?? result?.segmentation.labels}
                editDisabled={running}
                editMode={editMode}
                onEditModeChange={setEditMode}
                activeLabel={activeLabel}
                onActiveLabelChange={setActiveLabel}
                editApiRef={editApiRef}
                onUndo={handleUndo}
                onRedo={handleRedo}
                canUndo={undoKinds.length > 0}
                canRedo={redoKinds.length > 0}
                onSave={handleSave}
                canSave={(dirty || maskDirty) && !saving}
                saveLabel={saving ? t("Saving…") : saveLabel}
                undoLabel={
                  undoKinds.at(-1) === "mask" ? t("Undo mask edit") : t("Undo")
                }
                onMaskStroke={handleMaskStroke}
                onMaskHistoryReset={handleMaskHistoryReset}
                onLegend={setLegend}
              />
            )}
          </div>
          {/* Plain words, one gesture per item: "window/level" meant nothing
              to the clinicians reading it. */}
          <div className="mt-2 text-xs text-slate-500">
            <span className="font-semibold text-slate-600">{t("Mouse on the picture:")}</span>
            <ul className="mt-1 grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
              <li>{t("Scroll the wheel: previous / next slice")}</li>
              <li>{t("Hold the left button and drag: brightness and contrast")}</li>
              <li>{t("Hold the right button and drag: zoom in / out")}</li>
              <li>{t("Hold the wheel down and drag: move the picture")}</li>
            </ul>
            <p className="mt-1">{t("No mouse (touchpad)? Use the ◀ ▶, ＋ －, brightness and contrast buttons just under the picture.")}</p>
          </div>
        </section>
        <div className="relative">
        <aside className="flex flex-col gap-5 lg:absolute lg:inset-0 lg:overflow-y-auto lg:pr-1">
          {/* What is wrong, beside the picture -- the full table is below. */}
          {result && detail?.has_mask && (
            <FindingsSummary
              grading={result.grading}
              original={fullResult?.grading}
              onJump={setTargetSlice}
              onShowInTable={(level, condition) =>
                setTableHighlight({ level, condition, nonce: Date.now() })
              }
            />
          )}
          {legend.length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="mb-2 flex items-center gap-2 text-base font-bold text-slate-800">
                <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
                {t("Structures")}
              </h2>
              {/* While editing, the legend IS the brush's picker: the doctor
                  reads a colour off the image and clicks it, with no detour
                  through a separate list of names. */}
              {editMode && (
                <p className="mb-2 text-xs text-slate-500">
                  {activeLabel == null ? (
                    <span className="font-medium text-amber-700">
                      {t("Click it on the image, or pick it here — the fill tools are off until a structure is chosen.")}
                    </span>
                  ) : (
                    t("Click a structure here, or point at it on the image, to switch what is painted.")
                  )}
                </p>
              )}
              <Legend
                entries={legend}
                onSelect={editMode ? setActiveLabel : undefined}
                activeId={activeLabel}
              />
            </div>
          )}
        </aside>
        </div>
        </div>

          {/* What the clinician is looking at, and in what order to work.
              With model B on, two models' answers sit on one page and only one
              of them is editable; saying so up front is what keeps a doctor
              from trying to correct model B or rating the wrong one. */}
          {(result || detail?.is_picture) && (
            <div className="rounded-lg border-2 border-teal-200 bg-teal-50/60 p-4">
              <p className="text-sm font-bold text-slate-800">
                {detail?.is_picture
                  ? t("This study is one picture, so only model B reads it:")
                  : modelBShown
                    ? t("This study has results from two AI models:")
                    : t("This study has the AI's results:")}
              </p>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                {!detail?.is_picture && (
                  <a href="#model-a" className="flex items-start gap-2 rounded-md bg-white p-2.5 text-sm text-slate-700 shadow-sm hover:ring-2 hover:ring-teal-300">
                    <ModelBadge model="A" />
                    <span>
                      <b>{t("Model A")}</b> — {t("the coloured structures on the image and the grade table, level by level. You can correct it: change a grade, then Save.")}
                    </span>
                  </a>
                )}
                {(modelBShown || detail?.is_picture) && (
                  <a href="#model-b" className="flex items-start gap-2 rounded-md bg-white p-2.5 text-sm text-slate-700 shadow-sm hover:ring-2 hover:ring-violet-300">
                    <ModelBadge model="B" />
                    <span>
                      <b>{t("Model B")}</b> — {t("yes/no for the whole image, for comparison only. It cannot be edited.")}
                    </span>
                  </a>
                )}
              </div>
              {!detail?.is_picture && <p className="mt-2 text-xs text-slate-600">
                {modelBShown
                  ? t("Steps: 1. check model A against the image and correct what is wrong · 2. compare with model B · 3. answer the survey (★ top right), which asks about each model separately.")
                  : t("Steps: check the result against the image, correct what is wrong, then answer the survey (★ top right).")}
              </p>}
            </div>
          )}

          {/* Abnormality grades — the single 11-label editable table */}
          <div id="model-a" className="w-full basis-full scroll-mt-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
              <ModelBadge model="A" />
              {t("Model A — abnormality grades")}
              <span className="text-xs font-normal text-slate-500">{t("(editable)")}</span>
            </h2>
            {runError && (
              <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {runError}
              </div>
            )}
            {result && missingCbamColumns(result.grading) && (
              <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <strong>{t("Canal and foraminal stenosis are missing.")}</strong>{" "}
                {t("They are graded around the lumbar discs found by the segmentation, and the segmentation of this study has no lumbar discs — only the other 8 labels are shown. Re-upload the study and run again; if it persists, check the segmentation.")}
              </div>
            )}
            {result && detail && !detail.has_mask ? (
              /* Grades are cut from the segmentation: each disc crop comes
                 from a label in the mask. A table sitting next to a viewport
                 with no segmentation drawn on it invites the reader to treat
                 the numbers as belonging to the image in front of them, which
                 they do not -- they are left over from an image that is gone.
                 Say so instead of showing them. */
              <p className="text-sm text-slate-500">
                {t("No segmentation for this study, so there is nothing these grades were measured from. Click “✨ Run AI grading” to segment and grade the current image.")}
              </p>
            ) : result ? (
              <>
                <GradeTable
                  grading={result.grading}
                  original={fullResult?.grading}
                  highlight={tableHighlight}
                  onJump={setTargetSlice}
                  onEditSeverity={handleEditSeverity}
                />
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {/* One pair of buttons for both kinds of edit: the label
                      names whichever comes off the timeline next, so it is
                      clear a mask edit is about to be reverted. */}
                  <button
                    onClick={handleUndo}
                    disabled={undoKinds.length === 0}
                    title={
                      undoKinds.at(-1) === "mask"
                        ? t("Undo mask edit (Ctrl+Z)")
                        : t("Undo (Ctrl+Z)")
                    }
                    data-testid="undo-button"
                    className={btn}
                  >
                    ↶ {undoKinds.at(-1) === "mask" ? t("Undo mask edit") : t("Undo")}
                  </button>
                  <button
                    onClick={handleRedo}
                    disabled={redoKinds.length === 0}
                    title={
                      redoKinds[0] === "mask"
                        ? t("Redo mask edit (Ctrl+Shift+Z)")
                        : t("Redo (Ctrl+Shift+Z)")
                    }
                    data-testid="redo-button"
                    className={btn}
                  >
                    ↷ {redoKinds[0] === "mask" ? t("Redo mask edit") : t("Redo")}
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={(!dirty && !maskDirty) || saving}
                    className="rounded-lg bg-gradient-to-r from-teal-600 to-cyan-500 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {saving ? t("Saving…") : saveLabel}
                  </button>
                  <a href={exportUrl(studyId!)} target="_blank" rel="noreferrer">
                    <span className={btn}>⬇ {t("Export")}</span>
                  </a>
                  {fullResult && (
                    <>
                      <a
                        href={fullGradingCsvUrl(studyId!)}
                        className={btn}
                        style={{ textDecoration: "none" }}
                      >
                        ⬇ CSV
                      </a>
                      <a
                        href={fullGradingJsonUrl(studyId!)}
                        className={btn}
                        style={{ textDecoration: "none" }}
                      >
                        ⬇ JSON
                      </a>
                    </>
                  )}
                  {(dirty || maskDirty) && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                      {t("unsaved")}
                    </span>
                  )}
                </div>
                {savedNote && (
                  <p className="mt-2 text-xs font-medium text-emerald-600">
                    {savedNote}
                  </p>
                )}
                <p className="mt-2 text-xs text-slate-400">
                  {t("Click a level to jump; change a severity, then Save.")}
                </p>
              </>
            ) : (
              !running && (
                <p className="text-sm text-slate-500">
                  {detail?.is_picture
                    ? t("This study is one picture (PNG/JPG), so model A cannot grade it — it needs an MRI series (DICOM .zip, NIfTI or MHA). Model B's result is below.")
                    : t("No AI results yet — click “✨ Run AI grading” (top right).")}
                </p>
              )
            )}
          </div>

          {/* Doctor feedback — corrections are queued for offline review */}
          {!detail?.is_picture && (
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
              <span className="h-4 w-1 rounded bg-gradient-to-b from-indigo-500 to-violet-500" />
              {t("Doctor feedback")}
            </h2>
            <p className="text-xs text-slate-600">
              {t("When you fix a grade in the table above and press “Save corrections”, the change is recorded as expert feedback. Send them when you are ready.")}
            </p>

            {result && fullResult && (
              <MyEdits
                grading={result.grading}
                original={fullResult.grading}
                unsaved={dirty}
                onRevert={handleRevertToAI}
              />
            )}

            {corrections && (
              <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-baseline justify-between text-xs">
                  <span className="text-slate-600">{t("Waiting to be sent")}</span>
                  <span className="text-lg font-bold text-indigo-600">
                    {corrections.pending}
                  </span>
                </div>
                <div className="mt-1 flex items-baseline justify-between text-xs text-slate-500">
                  <span>{t("Already sent")}</span>
                  <span>
                    {corrections.submitted}
                    {corrections.batches > 0 &&
                      ` (${t("{n} batch(es)", { n: corrections.batches })})`}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={handleSubmitCorrections}
                  disabled={corrections.pending === 0 || submittingCorrections}
                  className="mt-3 w-full rounded-md bg-indigo-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {submittingCorrections
                    ? t("Sending…")
                    : t("Send {n} correction(s)", { n: corrections.pending })}
                </button>

                {submitMessage && (
                  <p className="mt-2 text-xs text-emerald-700">{submitMessage}</p>
                )}
              </div>
            )}

            <p className="mt-2 text-xs text-slate-400">
              {t("Sent corrections are reviewed later; they do not change the next patient's result.")}
            </p>
          </div>

          )}

          {/* Model B, for comparison only: renders nothing until our own
              grading exists, and nothing at all if model B is absent. */}
          {studyId && ((fullResult && result) || detail?.is_picture) && (
            <ReferenceBPanel
              studyId={studyId}
              gradedAt={fullResult}
              modelA={detail?.is_picture ? null : result?.grading}
              // A picture is uploaded to be read by model B: show it even
              // while the operator keeps model B hidden on scans.
              alwaysShow={!!detail?.is_picture}
            />
          )}

        <div className="flex flex-col gap-5">

          {/* Open by default: clinicians asked to see the meaning of each
              grade without hunting for it. */}
          <details open className="w-full basis-full rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <summary className="flex cursor-pointer items-center gap-2 text-base font-bold text-slate-800">
              <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
              {t("Label reference: what each grade means")}
            </summary>
            <div className="mt-3">
              <LabelReference />
            </div>
          </details>
        </div>
      </main>
    </div>
  );
}
