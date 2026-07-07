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
  type StudyOut,
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

/** MRN-style id, e.g. patient 1 -> "MRN-0001" (mirrors a real worklist). */
const mrn = (id: number) => `MRN-${String(id).padStart(4, "0")}`;
const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString();

export default function PatientList() {
  const [backend, setBackend] = useState<BackendStatus>({ state: "loading" });
  const [patients, setPatients] = useState<PatientOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  // Toolbar: search + modality filter.
  const [search, setSearch] = useState("");
  const [modalityFilter, setModalityFilter] = useState("All");

  // Collapsed patient groups (default: all expanded).
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  // Create-study form.
  const [showNew, setShowNew] = useState(false);
  const [newId, setNewId] = useState("");
  const [newPatient, setNewPatient] = useState("");
  const [newModality, setNewModality] = useState("MRI");

  // Patient rename (group header).
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");

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

  async function handleRename(patient: PatientOut) {
    const name = renameValue.trim();
    setRenamingId(null);
    if (!name || name === patient.name || patient.studies.length === 0) return;
    setError(null);
    try {
      // Renaming any of the patient's studies renames the shared patient row.
      await updateStudy(patient.studies[0].id, { patient_name: name });
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

  function toggle(id: number) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Apply search + modality filter, keeping only patients with matches.
  const q = search.trim().toLowerCase();
  const groups = patients
    .map((patient) => ({
      patient,
      studies: patient.studies.filter(
        (s) =>
          (modalityFilter === "All" || s.modality === modalityFilter) &&
          (q === "" ||
            patient.name.toLowerCase().includes(q) ||
            s.id.toLowerCase().includes(q) ||
            mrn(patient.id).toLowerCase().includes(q)),
      ),
    }))
    .filter((g) => g.studies.length > 0);

  const totalStudies = groups.reduce((n, g) => n + g.studies.length, 0);
  const modalities = [
    "All",
    ...new Set(patients.flatMap((p) => p.studies.map((s) => s.modality))),
  ];

  return (
    <div className="min-h-screen">
      {/* Brand header */}
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
        {/* Toolbar: title + search + filter + new */}
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h2 className="text-xl font-bold text-slate-800">Worklist</h2>
            <p className="text-sm text-slate-500">
              {groups.length} {groups.length === 1 ? "patient" : "patients"} ·{" "}
              {totalStudies} {totalStudies === 1 ? "study" : "studies"}
            </p>
          </div>
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
              ⌕
            </span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search patient, MRN, study…"
              className="w-64 rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm text-slate-800 shadow-sm focus:border-teal-500 focus:outline-none"
            />
          </div>
          <select
            value={modalityFilter}
            onChange={(e) => setModalityFilter(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
          >
            {modalities.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
          <button
            onClick={() => setShowNew((v) => !v)}
            className="rounded-lg bg-gradient-to-r from-teal-600 to-cyan-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:brightness-110"
          >
            {showNew ? "Cancel" : "+ New study"}
          </button>
        </div>

        {showNew && (
          <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
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
                placeholder="existing name groups; new one creates a patient"
                className="w-72 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-slate-800"
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

        {/* Patient groups (accordion) */}
        <div className="space-y-3">
          {groups.map(({ patient, studies }) => {
            const open = !collapsed.has(patient.id);
            const readyCount = studies.filter((s) => s.has_volume).length;
            return (
              <div
                key={patient.id}
                className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
              >
                {/* Patient header */}
                <div className="flex items-center gap-3 px-4 py-3">
                  <button
                    onClick={() => toggle(patient.id)}
                    className="flex flex-1 items-center gap-3 text-left"
                  >
                    <span
                      className={`text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}
                    >
                      ▸
                    </span>
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-teal-100 text-sm font-bold text-teal-700">
                      {initials(patient.name)}
                    </span>
                    <span>
                      {renamingId === patient.id ? (
                        <input
                          autoFocus
                          value={renameValue}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onBlur={() => handleRename(patient)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleRename(patient);
                            if (e.key === "Escape") setRenamingId(null);
                          }}
                          className="rounded border border-slate-300 px-2 py-0.5 text-sm"
                        />
                      ) : (
                        <span className="font-semibold text-slate-800">
                          {patient.name}
                        </span>
                      )}
                      <span className="ml-2 font-mono text-xs text-slate-400">
                        {mrn(patient.id)}
                      </span>
                    </span>
                  </button>
                  <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                    {studies.length} {studies.length === 1 ? "study" : "studies"}
                    {readyCount < studies.length &&
                      ` · ${readyCount} ready`}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setRenamingId(patient.id);
                      setRenameValue(patient.name);
                    }}
                    title="Rename patient"
                    className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50"
                  >
                    ✎
                  </button>
                </div>

                {/* Studies */}
                {open && (
                  <div className="border-t border-slate-100">
                    {studies.map((study: StudyOut) => (
                      <div
                        key={study.id}
                        className="flex items-center gap-3 border-b border-slate-50 px-4 py-2.5 pl-12 last:border-b-0 hover:bg-teal-50/40"
                      >
                        <span className="w-40 font-medium text-slate-800">
                          {study.id}
                        </span>
                        <span className="rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">
                          {study.modality}
                        </span>
                        <span className="text-xs text-slate-400">
                          {fmtDate(study.created_at)}
                        </span>
                        <span className="flex-1" />
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
                          onClick={() => fileInputs.current[study.id]?.click()}
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
                          onClick={() => handleDelete(study.id)}
                          title="Delete study"
                          className="rounded-lg border border-rose-200 px-2 py-1.5 text-xs text-rose-500 hover:bg-rose-50"
                        >
                          🗑
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {groups.length === 0 && (
            <div className="rounded-xl border border-slate-200 bg-white px-5 py-12 text-center text-slate-400 shadow-sm">
              {patients.length === 0
                ? "No studies yet — create one to get started."
                : "No matches for the current search / filter."}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
