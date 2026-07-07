import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  createStudy,
  deleteStudy,
  getHealth,
  getPatients,
  updateStudy,
  uploadStudy,
  type PatientOut,
} from "../lib/api";

type BackendStatus =
  | { state: "loading" }
  | { state: "ok"; status: string }
  | { state: "error"; message: string };

function StatusPill({ backend }: { backend: BackendStatus }) {
  const map = {
    loading: { text: "Connecting", cls: "bg-amber-100 text-amber-700", dot: "bg-amber-500" },
    ok: { text: "Online", cls: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
    error: { text: "Offline", cls: "bg-rose-100 text-rose-700", dot: "bg-rose-500" },
  }[backend.state];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${map.cls}`}
      title={backend.state === "error" ? backend.message : undefined}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${map.dot}`} />
      {map.text}
    </span>
  );
}

export default function PatientList() {
  const [backend, setBackend] = useState<BackendStatus>({ state: "loading" });
  const [patients, setPatients] = useState<PatientOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  // Create-study form.
  const [showNew, setShowNew] = useState(false);
  const [newId, setNewId] = useState("");
  const [newPatient, setNewPatient] = useState("");
  const [newModality, setNewModality] = useState("MRI");

  // Inline row editing.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editModality, setEditModality] = useState("");

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

  async function handleCreate() {
    const id = newId.trim();
    if (!id || !newPatient.trim()) return;
    setError(null);
    try {
      await createStudy(id, newPatient.trim(), newModality);
      setShowNew(false);
      setNewId("");
      setNewPatient("");
      setNewModality("MRI");
      loadPatients();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function startEdit(studyId: string, name: string, modality: string) {
    setEditingId(studyId);
    setEditName(name);
    setEditModality(modality);
  }

  async function handleSaveEdit() {
    if (!editingId) return;
    setError(null);
    try {
      await updateStudy(editingId, {
        patient_name: editName,
        modality: editModality,
      });
      setEditingId(null);
      loadPatients();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDelete(studyId: string) {
    if (!window.confirm(`Delete study "${studyId}"? This cannot be undone.`))
      return;
    setError(null);
    try {
      await deleteStudy(studyId);
      loadPatients();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const rows = patients.flatMap((patient) =>
    patient.studies.map((study) => ({ patient, study })),
  );

  return (
    <div className="min-h-screen">
      {/* Colorful brand header */}
      <header className="bg-gradient-to-r from-teal-600 to-cyan-500 shadow-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/20 text-lg backdrop-blur">
              🩻
            </div>
            <div>
              <h1 className="text-lg font-bold leading-tight text-white">
                Spine Labeling
              </h1>
              <p className="text-xs text-teal-50/90">
                Lumbar MRI · AI-assisted grading
              </p>
            </div>
          </div>
          <StatusPill backend={backend} />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-4 flex items-end justify-between">
          <div>
            <h2 className="text-xl font-bold text-slate-800">Patients</h2>
            <p className="text-sm text-slate-500">
              {rows.length} {rows.length === 1 ? "study" : "studies"} in the
              worklist
            </p>
          </div>
          <button
            onClick={() => setShowNew((v) => !v)}
            className="rounded-lg bg-gradient-to-r from-teal-600 to-cyan-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:brightness-110"
          >
            {showNew ? "Cancel" : "+ New study"}
          </button>
        </div>

        {showNew && (
          <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
              Study ID
              <input
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                placeholder="e.g. case_042"
                className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-slate-800"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
              Patient name
              <input
                value={newPatient}
                onChange={(e) => setNewPatient(e.target.value)}
                placeholder="e.g. Nguyen Van A"
                className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-slate-800"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
              Modality
              <select
                value={newModality}
                onChange={(e) => setNewModality(e.target.value)}
                className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-slate-800"
              >
                <option>MRI</option>
                <option>CT</option>
                <option>X-ray</option>
              </select>
            </label>
            <button
              onClick={handleCreate}
              disabled={!newId.trim() || !newPatient.trim()}
              className="rounded-lg bg-teal-600 px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-teal-700 disabled:opacity-40"
            >
              Create
            </button>
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">
            {error}
          </div>
        )}

        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-5 py-3">Study</th>
                <th className="px-5 py-3">Patient</th>
                <th className="px-5 py-3">Modality</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(({ patient, study }) => {
                const editing = editingId === study.id;
                return (
                  <tr
                    key={study.id}
                    className="transition-colors hover:bg-teal-50/40"
                  >
                    <td className="px-5 py-3 font-semibold text-slate-800">
                      {study.id}
                    </td>
                    <td className="px-5 py-3 text-slate-700">
                      {editing ? (
                        <input
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          className="w-40 rounded-md border border-slate-300 px-2 py-1 text-sm"
                        />
                      ) : (
                        patient.name
                      )}
                    </td>
                    <td className="px-5 py-3">
                      {editing ? (
                        <select
                          value={editModality}
                          onChange={(e) => setEditModality(e.target.value)}
                          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                        >
                          <option>MRI</option>
                          <option>CT</option>
                          <option>X-ray</option>
                        </select>
                      ) : (
                        <span className="rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">
                          {study.modality}
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      {study.has_volume ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                          Ready
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                          No volume
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex items-center justify-end gap-2">
                        {editing ? (
                          <>
                            <button
                              onClick={handleSaveEdit}
                              className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-teal-700"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setEditingId(null)}
                              className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                            >
                              Cancel
                            </button>
                          </>
                        ) : (
                          <>
                            <input
                              ref={(el) => {
                                fileInputs.current[study.id] = el;
                              }}
                              type="file"
                              accept=".mha,.nii,.nii.gz,.dcm"
                              className="hidden"
                              disabled={uploading === study.id}
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) handleUpload(study.id, file);
                              }}
                            />
                            <button
                              onClick={() =>
                                fileInputs.current[study.id]?.click()
                              }
                              disabled={uploading === study.id}
                              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50 disabled:opacity-50"
                            >
                              {uploading === study.id
                                ? "Uploading…"
                                : study.has_volume
                                  ? "Replace"
                                  : "Upload"}
                            </button>
                            {study.has_volume ? (
                              <Link
                                to={`/viewer/${study.id}`}
                                className="rounded-lg bg-gradient-to-r from-teal-600 to-cyan-500 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:brightness-110"
                              >
                                Open →
                              </Link>
                            ) : (
                              <span className="cursor-not-allowed rounded-lg bg-slate-100 px-3.5 py-1.5 text-xs font-semibold text-slate-400">
                                Open
                              </span>
                            )}
                            <button
                              onClick={() =>
                                startEdit(study.id, patient.name, study.modality)
                              }
                              title="Edit"
                              className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-50"
                            >
                              ✎
                            </button>
                            <button
                              onClick={() => handleDelete(study.id)}
                              title="Delete"
                              className="rounded-lg border border-rose-200 px-2 py-1.5 text-xs text-rose-500 hover:bg-rose-50"
                            >
                              🗑
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-12 text-center text-slate-400">
                    No studies yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
