import { Link, useParams } from "react-router-dom";
import CornerstoneViewport from "../components/Viewer/CornerstoneViewport";
import { API_BASE_URL } from "../lib/api";

export default function Viewer() {
  const { studyId } = useParams<{ studyId: string }>();

  return (
    <div style={{ padding: "1rem", fontFamily: "sans-serif" }}>
      <p>
        <Link to="/">← back to patients</Link>
      </p>
      <h1>Viewer — study {studyId}</h1>
      <p style={{ color: "#666" }}>
        Wheel: scroll slices · Left drag: window/level · Middle drag: pan ·
        Right drag: zoom
      </p>
      {studyId && (
        <CornerstoneViewport studyId={studyId} apiBaseUrl={API_BASE_URL} />
      )}
    </div>
  );
}
