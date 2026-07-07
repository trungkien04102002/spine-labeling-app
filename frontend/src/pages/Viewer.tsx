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

  return (
    <div style={{ padding: "1rem", fontFamily: "sans-serif", textAlign: "left" }}>
      <p>
        <Link to="/">← back to patients</Link>
      </p>
      <h1 style={{ textAlign: "center" }}>Viewer — study {studyId}</h1>
      <p style={{ color: "#666", marginTop: 0 }}>
        Wheel: scroll slices · Left drag: window/level · Middle drag: pan · Right
        drag: zoom
      </p>

      <div
        style={{
          display: "flex",
          gap: "1rem",
          alignItems: "flex-start",
          flexWrap: "wrap",
        }}
      >
        <div style={{ flex: "2 1 480px", minWidth: 0 }}>
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

        <aside style={{ flex: "1 1 320px", minWidth: 280 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: "0.5rem",
            }}
          >
            <h3 style={{ margin: 0 }}>Abnormality grades</h3>
            <button onClick={handleRunAI} disabled={running}>
              {running ? "Running AI… (~10 min)" : "Run AI"}
            </button>
          </div>
          {runError && <p style={{ color: "crimson" }}>{runError}</p>}
          {result ? (
            <>
              <GradeTable
                grading={result.grading}
                onJump={setTargetSlice}
                onEditSeverity={handleEditSeverity}
              />
              <div
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  alignItems: "center",
                  marginTop: 8,
                }}
              >
                <button
                  onClick={handleUndo}
                  disabled={!gradeHistory.canUndo}
                  title="Undo (Ctrl+Z)"
                >
                  ↶ Undo
                </button>
                <button
                  onClick={handleRedo}
                  disabled={!gradeHistory.canRedo}
                  title="Redo (Ctrl+Shift+Z)"
                >
                  ↷ Redo
                </button>
                <button
                  onClick={handleSave}
                  disabled={(!dirty && !maskDirty) || saving}
                >
                  {saving
                    ? "Saving…"
                    : dirty || maskDirty
                      ? "Save corrections"
                      : "Saved"}
                </button>
                <a href={exportUrl(studyId!)} target="_blank" rel="noreferrer">
                  <button>Export</button>
                </a>
                {(dirty || maskDirty) && (
                  <span style={{ color: "#c60", fontSize: "0.8rem" }}>
                    unsaved edits
                  </span>
                )}
              </div>
              {savedNote && (
                <p style={{ color: "green", fontSize: "0.8rem" }}>{savedNote}</p>
              )}
              <p style={{ color: "#888", fontSize: "0.75rem", marginTop: 8 }}>
                Model: {result.model_version}. Click a level to jump to that disc;
                change a severity, then Save.
              </p>
            </>
          ) : (
            !running && (
              <p style={{ color: "#888" }}>
                No AI results yet — click “Run AI”.
              </p>
            )
          )}

          {legend.length > 0 && (
            <div style={{ marginTop: "1rem" }}>
              <Legend entries={legend} />
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
