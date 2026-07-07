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

function BackendPill({ backend }: { backend: BackendStatus }) {
  const map = {
    loading: { dot: "bg-amber-400", text: "Connecting…", cls: "text-amber-700 bg-amber-50 ring-amber-200" },
    ok: { dot: "bg-emerald-500", text: "Online", cls: "text-emerald-700 bg-emerald-50 ring-emerald-200" },
    error: { dot: "bg-rose-500", text: "Offline", cls: "text-rose-700 bg-rose-50 ring-rose-200" },
  }[backend.state];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${map.cls}`}
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

  const rows = patients.flatMap((patient) =>
    patient.studies.map((study) => ({ patient, study })),
  );
  const studyCount = rows.length;

  return (
    <div className="min-h-screen bg-slate-100">
      {/* App header */}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
              S
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight text-slate-900">
                SpineLabel
              </h1>
              <p className="text-xs text-slate-500">Lumbar MRI labeling</p>
            </div>
          </div>
          <BackendPill backend={backend} />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-5 flex items-end justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Worklist</h2>
            <p className="text-sm text-slate-500">
              {studyCount} {studyCount === 1 ? "study" : "studies"}
            </p>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">
            {error}
          </div>
        )}

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-5 py-3">Study</th>
                <th className="px-5 py-3">Patient</th>
                <th className="px-5 py-3">Modality</th>
                <th className="px-5 py-3">Volume</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(({ patient, study }) => (
                <tr key={study.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3 font-medium text-slate-900">
                    {study.id}
                  </td>
                  <td className="px-5 py-3 text-slate-700">{patient.name}</td>
                  <td className="px-5 py-3">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                      {study.modality}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    {study.has_volume ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                        Ready
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-400">
                        <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                        No volume
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center justify-end gap-2">
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
                        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
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
                          className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
                        >
                          Open
                        </Link>
                      ) : (
                        <span className="cursor-not-allowed rounded-md bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-400">
                          Open
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-10 text-center text-slate-400">
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
