import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  createStudy,
  deleteStudy,
  getHealth,
  getPatients,
  getMyRoom,
  getSamples,
  addSample,
  type SampleOut,
  updateStudy,
  uploadStudy,
  type PatientOut,
  type StudyOut,
} from "../lib/api";
import PinSetup from "../components/PinSetup";
import { LangToggle, useT } from "../lib/i18n";
import { displayStudyId, useRoom } from "../lib/room";

type BackendStatus =
  | { state: "loading" }
  | { state: "ok"; status: string }
  | { state: "error"; message: string };

function StatusPill({ backend }: { backend: BackendStatus }) {
  const { t } = useT();
  const map = {
    loading: { text: t("Connecting"), cls: "bg-amber-100 text-amber-700", dot: "bg-amber-500" },
    ok: { text: t("Online"), cls: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
    error: { text: t("Offline"), cls: "bg-rose-100 text-rose-700", dot: "bg-rose-500" },
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
/** DICOM says "MR"; clinicians say MRI. Every study here is one. */
const showModality = (m: string) => (m === "MR" ? "MRI" : m);

export default function PatientList() {
  const { t } = useT();
  const { room, leave } = useRoom();
  const [backend, setBackend] = useState<BackendStatus>({ state: "loading" });
  const [patients, setPatients] = useState<PatientOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [noPin, setNoPin] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  // Toolbar: search. (No modality filter: this tool reads lumbar MRI only.)
  const [search, setSearch] = useState("");

  // Collapsed patient groups (default: all expanded).
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  // Create-study form.
  const [showNew, setShowNew] = useState(false);
  const [newId, setNewId] = useState("");
  const [newPatient, setNewPatient] = useState("");

  // Patient rename (group header).
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // Graded sample cases a clinician can copy into their room to try the tool
  // before bringing their own scans.
  const [samples, setSamples] = useState<SampleOut[]>([]);
  const [addingSample, setAddingSample] = useState<string | null>(null);
  const [showSamples, setShowSamples] = useState(false);
  const loadSamples = useCallback(() => {
    getSamples().then(setSamples).catch(() => setSamples([]));
  }, []);

  // Rooms from before PINs, rooms reset in /admin, and anyone who came in
  // by personal link without ever setting one: ask here, not only at the door.
  useEffect(() => {
    getMyRoom().then((r) => setNoPin(!r.has_pin)).catch(() => {});
  }, []);

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
    loadSamples();
  }, [loadPatients, loadSamples]);

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
      await createStudy(id, newPatient.trim(), "MRI");
      setShowNew(false);
      setNewId("");
      setNewPatient("");
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
    if (!window.confirm(t('Delete study "{id}"? This cannot be undone.', { id: studyId })))
      return;
    setError(null);
    try {
      await deleteStudy(studyId);
      loadPatients();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleAddSample(sampleId: string) {
    if (!room) return;
    setAddingSample(sampleId);
    setError(null);
    try {
      await addSample(room.id, sampleId);
      loadPatients();
      loadSamples();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddingSample(null);
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

  // Apply the search, keeping only patients with matches.
  const q = search.trim().toLowerCase();
  const groups = patients
    .map((patient) => ({
      patient,
      studies: patient.studies.filter(
        (s) =>
          (q === "" ||
            patient.name.toLowerCase().includes(q) ||
            s.id.toLowerCase().includes(q) ||
            mrn(patient.id).toLowerCase().includes(q)),
      ),
    }))
    .filter((g) => g.studies.length > 0);

  const totalStudies = groups.reduce((n, g) => n + g.studies.length, 0);

  return (
    <div className="min-h-screen">
      {/* Brand header */}
      <header className="bg-gradient-to-r from-teal-600 to-cyan-500 shadow-md">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/20 text-lg backdrop-blur">
              🩻
            </div>
            <div>
              <h1 className="text-lg font-bold leading-tight text-white">
                {t("Spine Labeling")}
              </h1>
              <p className="text-xs text-teal-50/90">
                {t("Lumbar MRI · AI-assisted grading")}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            {/* The room, and the way out of it. The operator's buttons that
                used to sit here (the correction queue, model versions) moved
                behind /admin: a clinician has no business switching the model
                that grades everyone else. */}
            <span className="flex items-center gap-2 whitespace-nowrap rounded-lg bg-white/15 px-3 py-1.5 text-xs text-white">
              <span className="text-teal-50/80">{t("Room")}</span>
              <span className="font-semibold">{room?.name}</span>
              <button
                type="button"
                onClick={leave}
                className="rounded border border-white/40 px-1.5 py-0.5 text-[10px] font-medium hover:bg-white/20"
              >
                {t("Switch")}
              </button>
            </span>
            <Link
              to="/survey"
              title={t("A short survey, about 5 minutes")}
              className="flex items-center gap-2 whitespace-nowrap rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-teal-700 shadow-sm transition hover:bg-teal-50"
            >
              <span>★ {t("Rate this software")}</span>
            </Link>
            <span className="hidden sm:inline-flex">
              <StatusPill backend={backend} />
            </span>
            <LangToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        {noPin && (
          <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
            <p className="text-sm font-semibold text-amber-800">
              {t("Your room has no PIN yet")}
            </p>
            <p className="mt-1 text-sm text-amber-800">
              {t("Choose a 4-digit PIN. Next time, pick your name on the first screen and type it to come back here.")}
            </p>
            <div className="max-w-xs">
              <PinSetup onDone={() => setNoPin(false)} />
            </div>
          </div>
        )}
        {/* What this site is for, before anything else: clinicians arrive
            from a link with no other introduction. Open until they close it. */}
        <details open className="mb-6 rounded-xl border border-teal-200 bg-white p-4 shadow-sm">
          <summary className="cursor-pointer text-sm font-bold text-teal-800">
            ⓘ {t("What is this website?")}
          </summary>
          <div className="mt-3 space-y-3 text-sm text-slate-700">
            <p>
              {t("It reads a lumbar spine MRI for you: the AI colours the vertebrae and discs on the image and grades what is abnormal at each disc level (T12–L1 down to L5–S1). You check the result and correct anything it got wrong.")}
            </p>
            <ol className="list-decimal space-y-1 pl-5">
              {/* Every step names the button to press, as it reads on screen:
                  "open the study" alone left clinicians looking for how. */}
              <li>{t("Press “+ New study”, type a study code and the patient's name, then press “Create”.")}</li>
              <li>
                {t("On the new study's row, press “Upload” and choose the scan, compressed into one .zip file.")}{" "}
                <mark className="rounded bg-amber-200 px-1 font-semibold text-slate-900">
                  {t("Only the sagittal (side view) lumbar series are needed, T2 first")}
                </mark>{" "}
                {t("— their names usually contain “sag”, e.g. t2_tse_sag, SAG T2, T2 SAG FSE.")}
              </li>
              <li>{t("When the study shows “Ready”, press “Open →”. On the study page press “✨ Run AI grading” at the top right: about 1–2 minutes, press it and leave it to run.")}</li>
              <li>{t("Look at the result, change any cell that is wrong, and press “Save corrections”.")}</li>
              <li>{t("When you are done, press “★ Rate this software” at the top right and answer the short survey (about 5 minutes).")}</li>
            </ol>
            <p className="text-xs text-slate-600">
              {t("Only have a picture (PNG/JPG), not the scan? Upload it the same way — then only model B reads it.")}
            </p>
            <a
              href="/huong-dan-su-dung.pdf"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-teal-300 bg-white px-3 py-1.5 text-sm font-semibold text-teal-700 hover:bg-teal-50"
            >
              📄 {t("User guide (PDF)")}
            </a>
            <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {t("Only sagittal lumbar series are graded. Axial (cross-section, “tra”/“ax”) and coronal (“cor”) series are not graded yet — no need to upload them. A research tool — not a diagnosis.")}
            </p>
          </div>
        </details>

        {/* Toolbar: title + search + new */}
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h2 className="text-xl font-bold text-slate-800">{t("Worklist")}</h2>
            <p className="text-sm text-slate-500">
              {t(groups.length === 1 ? "{n} patient" : "{n} patients", { n: groups.length })} ·{" "}
              {t(totalStudies === 1 ? "{n} study" : "{n} studies", { n: totalStudies })}
            </p>
          </div>
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
              ⌕
            </span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("Search patient, MRN, study…")}
              className="w-64 rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm text-slate-800 shadow-sm focus:border-teal-500 focus:outline-none"
            />
          </div>
          <button
            onClick={() => setShowNew((v) => !v)}
            className="rounded-lg bg-gradient-to-r from-teal-600 to-cyan-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:brightness-110"
          >
            {showNew ? t("Cancel") : t("+ New study")}
          </button>
          {samples.length > 0 && patients.length > 0 && (
            <button
              type="button"
              onClick={() => setShowSamples((v) => !v)}
              className="rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm font-medium text-teal-700 shadow-sm hover:bg-teal-50"
            >
              {showSamples ? t("Hide samples") : t("+ Sample case")}
            </button>
          )}
        </div>

        {showNew && (
          <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
              {t("Study ID")}
              <input
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                placeholder={t("e.g. case_042")}
                className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-slate-800"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
              {t("Patient name")}
              <input
                value={newPatient}
                onChange={(e) => setNewPatient(e.target.value)}
                placeholder={t("existing name groups; new one creates a patient")}
                className="w-72 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-slate-800"
              />
            </label>
            <button
              onClick={handleCreate}
              disabled={!newId.trim() || !newPatient.trim()}
              className="rounded-lg bg-teal-600 px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-teal-700 disabled:opacity-40"
            >
              {t("Create")}
            </button>
          </div>
        )}

        {/* Sample cases: open by default in an empty room, where they are the
            quickest way to see what the tool does; tucked away once the room
            has work of its own. */}
        {samples.length > 0 && (showSamples || patients.length === 0) && (
          <div className="mb-4 rounded-xl border border-teal-200 bg-teal-50/60 p-4">
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="text-sm font-bold text-slate-800">{t("Sample cases to try")}</h3>
              <p className="text-xs text-slate-600">
                {t("Already graded by the AI. Your copy is yours alone — edit it freely.")}
              </p>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {samples.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  disabled={s.added || addingSample !== null}
                  onClick={() => handleAddSample(s.id)}
                  className={
                    "rounded-lg border px-3 py-1.5 text-xs font-medium transition " +
                    (s.added
                      ? "border-slate-200 bg-white text-slate-400"
                      : "border-teal-300 bg-white text-teal-700 hover:bg-teal-50 disabled:opacity-50")
                  }
                >
                  {s.added ? `✓ ${s.id}` : addingSample === s.id ? t("Adding…") : `+ ${s.id}`}
                </button>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">
            {t(error)}
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
                    {t(studies.length === 1 ? "{n} study" : "{n} studies", { n: studies.length })}
                    {readyCount < studies.length &&
                      ` · ${t("{n} ready", { n: readyCount })}`}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setRenamingId(patient.id);
                      setRenameValue(patient.name);
                    }}
                    title={t("Rename patient")}
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
                        className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-50 px-4 py-2.5 last:border-b-0 hover:bg-teal-50/40 sm:pl-12"
                      >
                        <span className="font-medium text-slate-800 sm:w-40">
                          {displayStudyId(study.id)}
                        </span>
                        <span className="rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">
                          {showModality(study.modality)}
                        </span>
                        <span className="text-xs text-slate-400">
                          {fmtDate(study.created_at)}
                        </span>
                        {/* The status and the buttons go together, and drop to
                            their own line when the row is too narrow: on a
                            phone they were cut off past the card's edge. */}
                        <div className="ml-auto flex items-center gap-2">
                        {study.has_volume ? (
                          <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                            {t("Ready")}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-400">
                            <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                            {t("No volume")}
                          </span>
                        )}
                        <input
                          ref={(el) => {
                            fileInputs.current[study.id] = el;
                          }}
                          type="file"
                          accept=".zip,.mha,.nii,.nii.gz,.dcm,.png,.jpg,.jpeg"
                          title={t("MRI: DICOM folder as .zip, or .mha / .nii / .nii.gz. Or one picture (.png / .jpg) for model B only.")}
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
                          className="whitespace-nowrap rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50 disabled:opacity-50"
                        >
                          {uploading === study.id
                            ? t("Uploading…")
                            : study.has_volume
                              ? t("Replace")
                              : t("Upload")}
                        </button>
                        {study.has_volume ? (
                          <Link
                            to={`/viewer/${study.id}`}
                            className="whitespace-nowrap rounded-lg bg-gradient-to-r from-teal-600 to-cyan-500 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:brightness-110"
                          >
                            {t("Open →")}
                          </Link>
                        ) : (
                          <span className="cursor-not-allowed rounded-lg bg-slate-100 px-3.5 py-1.5 text-xs font-semibold text-slate-400">
                            {t("Open")}
                          </span>
                        )}
                        <button
                          onClick={() => handleDelete(study.id)}
                          title={t("Delete study")}
                          className="rounded-lg border border-rose-200 px-2 py-1.5 text-xs text-rose-500 hover:bg-rose-50"
                        >
                          🗑
                        </button>
                        </div>
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
                ? t("Your room is empty. Add a sample case above, or create a study and upload your own scan.")
                : t("No matches for the current search / filter.")}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
