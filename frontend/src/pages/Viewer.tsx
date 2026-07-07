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
  getAnnotation,
  getStudyDetail,
  runInference,
  saveAnnotation,
  saveMask,
  type InferResult,
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

export default function Viewer() {
  const { studyId } = useParams<{ studyId: string }>();
  const [detail, setDetail] = useState<StudyDetail | null>(null);
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

  useEffect(() => {
    if (!studyId) return;
    getStudyDetail(studyId)
      .then(setDetail)
      .catch(() => setDetail(null));
    getAnnotation(studyId)
      .then((r) => {
        gradeHistory.reset(r);
        setDirty(false);
      })
      .catch(() => gradeHistory.reset(null)); // 404 = inference not run yet
    // gradeHistory identity is stable; only re-run when the study changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId]);

  async function handleRunAI() {
    if (!studyId) return;
    setRunning(true);
    setRunError(null);
    try {
      const res = await runInference(studyId);
      gradeHistory.reset(res);
      setDirty(false);
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
            {running ? "Running AI… (~10 min)" : "✨ Run AI"}
          </button>
        </div>
      </header>

      <main className="mx-auto flex max-w-7xl flex-wrap items-start gap-5 px-6 py-6">
        {/* Viewer */}
        <section className="min-w-0 flex-[3_1_400px]">
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            {studyId && (
              <CornerstoneViewport
                studyId={studyId}
                apiBaseUrl={API_BASE_URL}
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
              </>
            ) : (
              !running && (
                <p className="text-sm text-slate-500">
                  No AI results yet — click “Run AI”.
                </p>
              )
            )}
          </div>

          {legend.length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <Legend entries={legend} />
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
