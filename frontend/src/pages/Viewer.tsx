import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CornerstoneViewport from "../components/Viewer/CornerstoneViewport";
import { API_BASE_URL, getStudyDetail, type StudyDetail } from "../lib/api";

/** Small label/value row for the study metadata panel. */
function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
      <span style={{ color: "#888" }}>{label}</span>
      <span style={{ fontWeight: 500 }}>{value}</span>
    </div>
  );
}

export default function Viewer() {
  const { studyId } = useParams<{ studyId: string }>();
  const [detail, setDetail] = useState<StudyDetail | null>(null);

  useEffect(() => {
    if (!studyId) return;
    getStudyDetail(studyId)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [studyId]);

  const dims = detail?.dimensions;
  const sp = detail?.spacing_mm;

  return (
    <div style={{ padding: "1rem", fontFamily: "sans-serif" }}>
      <p>
        <Link to="/">← back to patients</Link>
      </p>
      <h1>Viewer — study {studyId}</h1>

      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
        {/* Patient / study / image metadata — mirrors a clinical viewer header. */}
        <aside
          style={{
            flex: "0 0 260px",
            fontSize: "0.85rem",
            border: "1px solid #ddd",
            borderRadius: 6,
            padding: "0.75rem",
            background: "#fafafa",
          }}
        >
          <h3 style={{ margin: "0 0 0.5rem" }}>Study info</h3>
          {detail ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <MetaRow label="Patient" value={detail.patient_name} />
              <MetaRow label="Patient ID" value={String(detail.patient_id)} />
              <MetaRow label="Study ID" value={detail.id} />
              <MetaRow label="Modality" value={detail.modality} />
              <MetaRow
                label="Acquired"
                value={new Date(detail.created_at).toLocaleString()}
              />
              {dims && (
                <MetaRow
                  label="Dimensions"
                  value={`${dims[0]} × ${dims[1]} × ${dims[2]}`}
                />
              )}
              {sp && (
                <MetaRow
                  label="Spacing (mm)"
                  value={`${sp[0]} × ${sp[1]} × ${sp[2]}`}
                />
              )}
              {detail.num_slices != null && (
                <MetaRow label="Slices" value={String(detail.num_slices)} />
              )}
              <MetaRow
                label="Segmentation"
                value={detail.has_mask ? "available" : "not run"}
              />
            </div>
          ) : (
            <p style={{ color: "#888" }}>Loading…</p>
          )}
        </aside>

        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ color: "#666", marginTop: 0 }}>
            Wheel: scroll slices · Left drag: window/level · Middle drag: pan ·
            Right drag: zoom
          </p>
          {studyId && (
            <CornerstoneViewport studyId={studyId} apiBaseUrl={API_BASE_URL} />
          )}
        </div>
      </div>
    </div>
  );
}
