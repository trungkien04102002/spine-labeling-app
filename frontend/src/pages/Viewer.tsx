import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CornerstoneViewport, {
  type LegendEntry,
  type MaskEditApi,
} from "../components/Viewer/CornerstoneViewport";
import GradeTable from "../components/Viewer/GradeTable";
import Legend from "../components/Viewer/Legend";
import { useHistory } from "../lib/history";
import {
  API_BASE_URL,
  exportUrl,
  fullGradingCsvUrl,
  fullGradingJsonUrl,
  fullGradingSliceUrl,
  getAnnotation,
  getFullGrading,
  getSeries,
  getStudyDetail,
  runFullGrading,
  saveAnnotation,
  saveMask,
  setActiveSeries,
  type FullGradingResult,
  type InferResult,
  type SeriesOut,
  type StudyDetail,
} from "../lib/api";

/**
 * Translucent metadata overlay pinned to a corner of the image, the way a PACS
 * workstation annotates the view. Patient/study identity sits top-left;
 * acquisition parameters (DICOM only) can be toggled open.
 */
function InfoOverlay({ detail }: { detail: StudyDetail }) {
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
        {detail.modality} · {new Date(detail.created_at).toLocaleDateString()}
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
            {showTags ? "▾ acquisition" : "▸ acquisition"}
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
// + standard lumbar-MRI radiology). `src` marks which model produces the column.
const PREDICTION_GUIDE: { name: string; scale: string; meaning: string; src: "SpineNet" | "CBAM" }[] = [
  { name: "Pfirrmann", scale: "5 grades (I–V)", meaning: "Disc degeneration, from healthy (I) to severely degenerated (V).", src: "SpineNet" },
  { name: "Disc narrowing", scale: "4 grades", meaning: "Loss of intervertebral disc height.", src: "SpineNet" },
  { name: "Central canal stenosis", scale: "4 grades", meaning: "Narrowing of the central spinal canal.", src: "CBAM" },
  { name: "Foraminal stenosis (L/R)", scale: "binary", meaning: "Narrowing of the left/right nerve-exit foramen.", src: "CBAM" },
  { name: "Spondylolisthesis", scale: "binary", meaning: "Forward slippage of one vertebra over another.", src: "SpineNet" },
  { name: "Endplate defects (upper/lower)", scale: "binary", meaning: "Damage to the vertebral endplate.", src: "SpineNet" },
  { name: "Marrow changes (upper/lower)", scale: "binary", meaning: "Modic vertebral bone-marrow signal changes.", src: "SpineNet" },
  { name: "Disc herniation", scale: "binary", meaning: "Protrusion/extrusion of disc material.", src: "SpineNet" },
];

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
  if (series.length < 2) return null;
  const analyzed = series.find((s) => s.analyzed_by_ai);
  return (
    <div className="border-b border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-semibold text-slate-500">
          Series
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
            {PLANE_LABEL[s.orientation] ?? "Series"}
            {s.description ? (
              <span className="ml-1 font-normal opacity-80">
                {s.description}
              </span>
            ) : null}
            {s.num_slices ? (
              <span className="ml-1 font-normal opacity-60">
                ({s.num_slices})
              </span>
            ) : null}
            {s.analyzed_by_ai ? (
              <span
                className={
                  "ml-1.5 rounded px-1 py-px text-[10px] font-bold " +
                  (s.is_active
                    ? "bg-white/25 text-white"
                    : "bg-teal-100 text-teal-700")
                }
              >
                AI
              </span>
            ) : null}
          </button>
        ))}
        {busy ? (
          <span className="ml-1 text-xs text-slate-500">Loading…</span>
        ) : null}
      </div>
      <p className="mt-1.5 text-[11px] leading-snug text-slate-500">
        {analyzed ? (
          <>
            The AI graded the series marked <strong>AI</strong> (
            {PLANE_LABEL[analyzed.orientation] ?? "series"}). Other series are
            for viewing; the model does not read them yet.
          </>
        ) : (
          <>
            All planes are viewable. &ldquo;Run AI&rdquo; grades the selected
            series only — the model reads one acquisition, not all of them.
          </>
        )}
      </p>
    </div>
  );
}

export default function Viewer() {
  const { studyId } = useParams<{ studyId: string }>();
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [series, setSeries] = useState<SeriesOut[]>([]);
  const [seriesBusy, setSeriesBusy] = useState(false);
  // Grade edits flow through an undo/redo history; `result` is its cursor.
  const gradeHistory = useHistory<InferResult | null>(null);
  const result = gradeHistory.state;
  const [targetSlice, setTargetSlice] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [maskDirty, setMaskDirty] = useState(false);
  const [legend, setLegend] = useState<LegendEntry[]>([]);
  const editApiRef = useRef<MaskEditApi | null>(null);

  // "Run AI" produces the full 11-label grading (SpineNet + CBAM) AND persists a
  // v0 annotation, so the editable `result` above IS the 11-label table. We keep
  // `fullResult` only for the extras the annotation doesn't carry: the labelled
  // slice image and the CSV/JSON download URLs.
  const [fullResult, setFullResult] = useState<FullGradingResult | null>(null);
  // Cache-busts the slice image <img> src (the URL itself never changes).
  const [sliceNonce, setSliceNonce] = useState(0);

  useEffect(() => {
    if (!studyId) return;
    getStudyDetail(studyId)
      .then(setDetail)
      .catch(() => setDetail(null));
    getSeries(studyId)
      .then(setSeries)
      .catch(() => setSeries([]));
    getAnnotation(studyId)
      .then((r) => {
        gradeHistory.reset(r);
        setDirty(false);
      })
      .catch(() => gradeHistory.reset(null)); // 404 = inference not run yet
    getFullGrading(studyId)
      .then((r) => {
        setFullResult(r);
        setSliceNonce((n) => n + 1);
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
  async function handleRunAI() {
    if (!studyId) return;
    setRunning(true);
    setRunError(null);
    try {
      const full = await runFullGrading(studyId);
      setFullResult(full);
      const ann = await getAnnotation(studyId);
      gradeHistory.reset(ann);
      setDirty(false);
      setSliceNonce((n) => n + 1);
      getStudyDetail(studyId).then(setDetail).catch(() => {});
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
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
    setDirty(true);
    setSavedNote(null);
  }

  function handleUndo() {
    if (!gradeHistory.canUndo) return;
    gradeHistory.undo();
    setDirty(true);
    setSavedNote(null);
  }

  function handleRedo() {
    if (!gradeHistory.canRedo) return;
    gradeHistory.redo();
    setDirty(true);
    setSavedNote(null);
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
      setSavedNote("Saved as a new corrected version.");
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const btn =
    "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed";

  return (
    <div className="min-h-screen">
      {/* Colorful brand header */}
      <header className="bg-gradient-to-r from-teal-600 to-cyan-500 shadow-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-3 text-white">
            <Link
              to="/"
              className="rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium backdrop-blur transition hover:bg-white/25"
            >
              ← Worklist
            </Link>
            <div className="leading-tight">
              <div className="text-sm font-bold">Study {studyId}</div>
              <div className="text-xs text-teal-50/90">
                {detail?.patient_name ?? "…"}
              </div>
            </div>
          </div>
          <button
            onClick={handleRunAI}
            disabled={running}
            className="rounded-lg bg-white px-4 py-1.5 text-sm font-semibold text-teal-700 shadow-sm transition hover:bg-teal-50 disabled:opacity-60"
          >
            {running ? "Running…" : "✨ Run AI"}
          </button>
        </div>
      </header>

      <main className="mx-auto flex max-w-7xl flex-wrap items-start gap-5 px-6 py-6">
        {/* Viewer */}
        <section className="min-w-0 flex-[3_1_400px]">
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <SeriesPicker
              series={series}
              busy={seriesBusy}
              onSelect={handleSelectSeries}
            />
            {studyId && (
              <CornerstoneViewport
                studyId={studyId}
                apiBaseUrl={API_BASE_URL}
                seriesKey={series.find((s) => s.is_active)?.id ?? null}
                overlay={detail ? <InfoOverlay detail={detail} /> : null}
                targetSlice={targetSlice}
                segLabels={result?.segmentation.labels}
                editApiRef={editApiRef}
                onMaskEdited={() => {
                  setMaskDirty(true);
                  setSavedNote(null);
                }}
                onLegend={setLegend}
              />
            )}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Wheel: scroll slices · Left drag: window/level · Middle drag: pan ·
            Right drag: zoom
          </p>
        </section>

        {/* Side panel */}
        <aside className="flex min-w-[260px] flex-[1_1_280px] flex-col gap-5">
          {/* About this tool — what it predicts + disclaimer (collapsible) */}
          <details className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <summary className="flex cursor-pointer items-center gap-2 text-base font-bold text-slate-800">
              <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
              About this tool
            </summary>
            <div className="mt-3 space-y-3 text-xs text-slate-600">
              <p>
                This tool automatically reads a lumbar spine MRI and produces
                radiological grades for each intervertebral disc level (T12–L1
                down to L5–S1). Click a level in the table to jump to its slice;
                you can correct any grade and save it.
              </p>
              <div>
                <p className="mb-1 font-semibold text-slate-700">
                  What it predicts
                </p>
                <ul className="space-y-1.5">
                  {PREDICTION_GUIDE.map((g) => (
                    <li key={g.name}>
                      <span className="font-medium text-slate-700">
                        {g.name}
                      </span>{" "}
                      <span className="text-slate-400">({g.scale})</span> —{" "}
                      {g.meaning}
                    </li>
                  ))}
                </ul>
              </div>
              <p className="text-slate-500">
                Central canal + left/right foraminal stenosis come from the
                project's fine-tuned <strong>CBAM</strong> model; the other 8
                grades come from the upstream <strong>SpineNet</strong> pipeline.
              </p>
              <p className="rounded-md bg-amber-50 px-2.5 py-1.5 text-amber-700">
                ⚠ Research use only — this is not a diagnostic tool or a medical
                device.
              </p>
            </div>
          </details>

          {legend.length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
                <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
                Structures
              </h2>
              <Legend entries={legend} />
            </div>
          )}

          {/* Abnormality grades — the single 11-label editable table */}
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
              <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
              Abnormality grades
            </h2>
            {runError && (
              <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {runError}
              </div>
            )}
            {result ? (
              <>
                <GradeTable
                  grading={result.grading}
                  onJump={setTargetSlice}
                  onEditSeverity={handleEditSeverity}
                />
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    onClick={handleUndo}
                    disabled={!gradeHistory.canUndo}
                    title="Undo (Ctrl+Z)"
                    className={btn}
                  >
                    ↶ Undo
                  </button>
                  <button
                    onClick={handleRedo}
                    disabled={!gradeHistory.canRedo}
                    title="Redo (Ctrl+Shift+Z)"
                    className={btn}
                  >
                    ↷ Redo
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={(!dirty && !maskDirty) || saving}
                    className="rounded-lg bg-gradient-to-r from-teal-600 to-cyan-500 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {saving
                      ? "Saving…"
                      : dirty || maskDirty
                        ? "Save corrections"
                        : "Saved"}
                  </button>
                  <a href={exportUrl(studyId!)} target="_blank" rel="noreferrer">
                    <span className={btn}>⬇ Export</span>
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
                      unsaved
                    </span>
                  )}
                </div>
                {savedNote && (
                  <p className="mt-2 text-xs font-medium text-emerald-600">
                    {savedNote}
                  </p>
                )}
                <p className="mt-2 text-xs text-slate-400">
                  Model: {result.model_version}. Click a level to jump; change a
                  severity, then Save.
                </p>
                {fullResult && (
                  <img
                    src={`${fullGradingSliceUrl(studyId!)}?v=${sliceNonce}`}
                    alt="SpineNet-labelled mid-sagittal slice"
                    className="mt-3 w-full rounded-lg border border-slate-200"
                  />
                )}
              </>
            ) : (
              !running && (
                <p className="text-sm text-slate-500">
                  No AI results yet — click “✨ Run AI” (top right).
                </p>
              )
            )}
          </div>

          {/* Doctor feedback — corrections feed the model over time */}
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
              <span className="h-4 w-1 rounded bg-gradient-to-b from-indigo-500 to-violet-500" />
              Doctor feedback
            </h2>
            <p className="text-xs text-slate-600">
              When you fix a grade in the table above and press{" "}
              <span className="font-medium text-slate-700">
                “Save corrections”
              </span>
              , the change is recorded as expert feedback. These corrections are
              collected and used to periodically re-train the model, so its
              predictions gradually improve with use.
            </p>
            <p className="mt-2 text-xs text-slate-400">
              Re-training runs offline in batches — you don't need to do anything
              beyond reviewing and saving.
            </p>
          </div>
        </aside>
      </main>
    </div>
  );
}
