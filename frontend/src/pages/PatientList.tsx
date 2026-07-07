import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  getHealth,
  getPatients,
  uploadStudy,
  type PatientOut,
} from "../lib/api";

type BackendStatus =
  | { state: "loading" }
  | { state: "ok"; status: string }
  | { state: "error"; message: string };

export default function PatientList() {
  const [backend, setBackend] = useState<BackendStatus>({ state: "loading" });
  const [patients, setPatients] = useState<PatientOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  const loadPatients = useCallback(() => {
    getPatients()
      .then(setPatients)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  }, []);

  useEffect(() => {
    getHealth()
      .then((res) => setBackend({ state: "ok", status: res.status }))
      .catch((err: unknown) =>
        setBackend({
          state: "error",
          message: err instanceof Error ? err.message : String(err),
        }),
      );
    loadPatients();
  }, [loadPatients]);

  async function handleUpload(studyId: string, file: File) {
    setUploading(studyId);
    setError(null);
    try {
      await uploadStudy(studyId, file);
      loadPatients();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(null);
    }
  }

  return (
    <div style={{ padding: "1rem", fontFamily: "sans-serif" }}>
      <h1>Patients</h1>

      <p>
        {backend.state === "loading" && "Backend: checking..."}
        {backend.state === "ok" && `Backend: ${backend.status}`}
        {backend.state === "error" && `Backend: error (${backend.message})`}
      </p>

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <table border={1} cellPadding={8} style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th>Study ID</th>
            <th>Patient</th>
            <th>Modality</th>
            <th>Volume</th>
            <th>Upload</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {patients.flatMap((patient) =>
            patient.studies.map((study) => (
              <tr key={study.id}>
                <td>{study.id}</td>
                <td>{patient.name}</td>
                <td>{study.modality}</td>
                <td>{study.has_volume ? "✓" : "—"}</td>
                <td>
                  <input
                    ref={(el) => {
                      fileInputs.current[study.id] = el;
                    }}
                    type="file"
                    accept=".mha,.nii,.nii.gz,.dcm"
                    disabled={uploading === study.id}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleUpload(study.id, file);
                    }}
                  />
                  {uploading === study.id && " uploading..."}
                </td>
                <td>
                  {study.has_volume ? (
                    <Link to={`/viewer/${study.id}`}>Open</Link>
                  ) : (
                    <span style={{ color: "#999" }}>Open</span>
                  )}
                </td>
              </tr>
            )),
          )}
          {patients.length === 0 && (
            <tr>
              <td colSpan={6}>No patients yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
