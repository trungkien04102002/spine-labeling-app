import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CornerstoneViewport from "../components/Viewer/CornerstoneViewport";
import GradeTable from "../components/Viewer/GradeTable";
import {
  API_BASE_URL,
  getAnnotation,
  getStudyDetail,
  runInference,
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
  const [result, setResult] = useState<InferResult | null>(null);
  const [targetSlice, setTargetSlice] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    if (!studyId) return;
    getStudyDetail(studyId)
      .then(setDetail)
      .catch(() => setDetail(null));
    getAnnotation(studyId)
      .then(setResult)
      .catch(() => setResult(null)); // 404 = inference not run yet
  }, [studyId]);

  async function handleRunAI() {
    if (!studyId) return;
    setRunning(true);
    setRunError(null);
    try {
      const res = await runInference(studyId);
      setResult(res);
      getStudyDetail(studyId).then(setDetail).catch(() => {});
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div style={{ padding: "1rem", fontFamily: "sans-serif" }}>
      <p>
        <Link to="/">← back to patients</Link>
      </p>
      <h1>Viewer — study {studyId}</h1>
      <p style={{ color: "#666", marginTop: 0 }}>
        Wheel: scroll slices · Left drag: window/level · Middle drag: pan · Right
        drag: zoom
      </p>

      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {studyId && (
            <CornerstoneViewport
              studyId={studyId}
              apiBaseUrl={API_BASE_URL}
              overlay={detail ? <InfoOverlay detail={detail} /> : null}
              targetSlice={targetSlice}
            />
          )}
        </div>

        <aside style={{ flex: "0 0 360px" }}>
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
              <GradeTable grading={result.grading} onJump={setTargetSlice} />
              <p style={{ color: "#888", fontSize: "0.75rem", marginTop: 8 }}>
                Model: {result.model_version}. Click a level to jump to that disc.
              </p>
            </>
          ) : (
            !running && (
              <p style={{ color: "#888" }}>
                No AI results yet — click “Run AI”.
              </p>
            )
          )}
        </aside>
      </div>
    </div>
  );
}
