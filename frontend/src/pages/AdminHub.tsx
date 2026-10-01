import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";

import Admin, { SurveyPanel } from "./Admin";
import ModelVersions from "./ModelVersions";
import {
  adminLogin,
  copyText,
  joinRoom,
  resetRoomPin,
  roomLink,
  deleteSurveyResponse,
  downloadLocked,
  getAdminStatus,
  getRooms,
  getSurveyForm,
  getSurveyResponses,
  type RoomSummary,
  type SurveyForm,
  type SurveyResponseOut,
} from "../lib/api";
import { LangToggle, useT } from "../lib/i18n";
import { readAdminKey, writeAdminKey } from "../lib/room";

/**
 * The operator's side of the app, in one place behind one passphrase.
 *
 * Clinicians never see a link to any of this: which rooms exist, what each
 * clinician answered, the export, switching the model, re-training. Before,
 * those were separate top-level pages a clinician reached from the worklist
 * header; now the worklist has no such buttons, and /models redirects here.
 */

type Gate = "checking" | "open" | "locked";

function LoginCard({ onOpen }: { onOpen: () => void }) {
  const { t } = useT();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await adminLogin(password);
      writeAdminKey(password);
      onOpen();
    } catch {
      setError(t("Wrong passphrase."));
    }
  }
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl bg-white p-7 shadow-lg">
        <h1 className="text-lg font-bold text-slate-800">{t("Admin")}</h1>
        <p className="mt-1 text-sm text-slate-500">{t("For whoever runs the trial.")}</p>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={t("Passphrase")}
          className="mt-5 w-full rounded-lg border-2 border-slate-200 px-3 py-2.5 focus:border-teal-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!password}
          className="mt-3 w-full rounded-lg bg-slate-800 py-2.5 font-semibold text-white disabled:bg-slate-300"
        >
          {t("Open")}
        </button>
        {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
        <Link to="/" className="mt-5 block text-center text-xs text-slate-400 hover:underline">
          {t("← Back to the clinician view")}
        </Link>
      </form>
    </div>
  );
}

const fmt = (iso: string) => new Date(iso).toLocaleString();

function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="flex items-center gap-2 text-base font-bold text-slate-800">
          <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
          {title}
        </h2>
        <div className="ml-auto">{action}</div>
      </div>
      {children}
    </section>
  );
}

/** A room's link with a copy button that also works over plain HTTP. */
function LinkCell({ code }: { code: string }) {
  const { t } = useT();
  const [copied, setCopied] = useState<"ok" | "fail" | null>(null);
  const link = roomLink(code);
  return (
    <span className="flex items-center gap-2">
      <input
        readOnly
        value={link}
        onFocus={(e) => e.currentTarget.select()}
        className="w-64 rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-600"
      />
      <button
        type="button"
        onClick={async () => {
          setCopied((await copyText(link)) ? "ok" : "fail");
          window.setTimeout(() => setCopied(null), 1800);
        }}
        className="whitespace-nowrap rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
      >
        {copied === "ok" ? t("✓ Copied") : copied === "fail" ? t("Select and copy") : t("Copy")}
      </button>
    </span>
  );
}

function RoomsPage() {
  const { t } = useT();
  const [rooms, setRooms] = useState<RoomSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    getRooms().then(setRooms).catch((e) => setError(String(e)));
  }, []);
  useEffect(load, [load]);

  // Creating a room is the same call as a clinician entering one: a name
  // that already exists returns that room, so this cannot make a duplicate.
  // Rooms made here have no PIN; the clinician chooses one on first entry.
  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await joinRoom(name.trim());
      setName("");
      load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(
        /wrong pin/i.test(msg)
          ? t("That name already has a room — its link is in the list below.")
          : msg,
      );
    } finally {
      setBusy(false);
    }
  }

  async function resetPin(r: RoomSummary) {
    if (!window.confirm(t("Reset the PIN of “{name}”? Their room opens without a PIN until they choose a new one.", { name: r.name }))) return;
    try {
      await resetRoomPin(r.id);
      load();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <Card title={t("Clinician rooms")}>
      <form onSubmit={create} className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("Clinician's name")}
          className="w-64 rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
        />
        <button
          type="submit"
          disabled={!name.trim() || busy}
          className="rounded-lg bg-teal-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-teal-700 disabled:bg-slate-300"
        >
          {t("+ Create room and link")}
        </button>
        <span className="text-xs text-slate-500">
          {t("Send each clinician their link. If they lose it or forget their PIN, copy it again from here — the link opens the room without a PIN.")}
        </span>
      </form>
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {rooms === null ? (
        <p className="text-sm text-slate-500">{t("Loading…")}</p>
      ) : rooms.length === 0 ? (
        <p className="text-sm text-slate-500">{t("Nobody has entered a room yet.")}</p>
      ) : (
        <div className="scroll-x-visible">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-2 pr-3">{t("Name")}</th>
                <th className="py-2 pr-3">{t("Personal link")}</th>
                <th className="py-2 pr-3">{t("PIN")}</th>
                <th className="py-2 pr-3">{t("Joined")}</th>
                <th className="py-2 pr-3 text-right">{t("Studies")}</th>
                <th className="py-2 pr-3 text-right">{t("Corrections")}</th>
                <th className="py-2 text-right">{t("Surveys")}</th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((r) => (
                <tr key={r.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-semibold text-slate-800">{r.name}</td>
                  <td className="py-2 pr-3"><LinkCell code={r.code} /></td>
                  <td className="py-2 pr-3 whitespace-nowrap">
                    {r.has_pin ? (
                      <>
                        <span className="text-emerald-700">{t("Set")}</span>{" "}
                        <button
                          type="button"
                          onClick={() => resetPin(r)}
                          className="ml-1 rounded border border-slate-300 px-1.5 py-0.5 text-[11px] text-slate-600 hover:bg-slate-100"
                        >
                          {t("Reset PIN")}
                        </button>
                      </>
                    ) : (
                      <span className="text-amber-700">{t("Not set yet")}</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-slate-500">{fmt(r.created_at)}</td>
                  <td className="py-2 pr-3 text-right">{r.studies}</td>
                  <td className="py-2 pr-3 text-right">{r.corrections}</td>
                  <td className="py-2 text-right">
                    {r.surveys > 0 ? (
                      <span className="rounded bg-teal-50 px-1.5 py-0.5 font-semibold text-teal-700">
                        {r.surveys}
                      </span>
                    ) : (
                      <span className="text-slate-300">0</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/**
 * Every questionnaire on its own, by room. The summary above it averages
 * clinicians together; this is where you find out which one said what, and
 * whether their comment explains an odd answer.
 */
function ResponsesList() {
  const { t } = useT();
  const [rows, setRows] = useState<SurveyResponseOut[] | null>(null);
  const [form, setForm] = useState<SurveyForm | null>(null);
  const [rooms, setRooms] = useState<Record<number, string>>({});
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(() => {
    getSurveyResponses().then(setRows).catch(() => setRows([]));
  }, []);
  useEffect(() => {
    load();
    getSurveyForm().then(setForm).catch(() => {});
    getRooms()
      .then((rs) => setRooms(Object.fromEntries(rs.map((r) => [r.id, r.name]))))
      .catch(() => {});
  }, [load]);

  async function remove(r: SurveyResponseOut) {
    const who = (r.reader_id && rooms[r.reader_id]) || r.respondent || `#${r.id}`;
    if (!window.confirm(t("Delete {who}'s response for good? Use this only for test submissions.", { who }))) return;
    await deleteSurveyResponse(r.id);
    load();
  }

  if (rows === null) return <p className="text-sm text-slate-500">{t("Loading…")}</p>;
  if (rows.length === 0) return <p className="text-sm text-slate-500">{t("No responses yet.")}</p>;

  return (
    <ul className="divide-y divide-slate-100">
      {rows.map((r) => {
        const who = (r.reader_id && rooms[r.reader_id]) || r.respondent || t("(no room)");
        const expanded = open === r.id;
        return (
          <li key={r.id} className="py-2">
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : r.id)}
                className="flex flex-1 items-center gap-3 text-left"
              >
                <span className="text-slate-400">{expanded ? "▾" : "▸"}</span>
                <span className="font-semibold text-slate-800">{who}</span>
                {r.role && <span className="text-xs text-slate-500">{r.role}</span>}
                <span className="text-xs text-slate-400">{fmt(r.submitted_at)}</span>
              </button>
              <span className="font-mono text-sm text-slate-700">
                {r.clinical_mean ?? "—"}
                <span className="text-slate-400"> / 5</span>
              </span>
              <button
                type="button"
                onClick={() => remove(r)}
                className="rounded border border-rose-200 px-2 py-0.5 text-xs text-rose-500 hover:bg-rose-50"
              >
                {t("Delete")}
              </button>
            </div>
            {expanded && (
              <div className="mt-2 pl-6">
                {r.comment && (
                  <p className="mb-2 rounded bg-slate-50 px-3 py-2 text-sm text-slate-700">
                    &ldquo;{r.comment}&rdquo;
                  </p>
                )}
                <table className="w-full text-xs">
                  <tbody>
                    {(form?.questions ?? []).map((q) => (
                      <tr key={q.id} className="border-t border-slate-100">
                        <td className="w-8 py-1 text-slate-400">{q.id}</td>
                        <td className="py-1 pr-3 text-slate-600">{q.text}</td>
                        <td className="w-10 py-1 text-right font-mono font-semibold text-slate-800">
                          {r.answers[String(q.id)] ?? <span className="text-slate-300">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function SurveyPage() {
  const { t } = useT();
  return (
    <div className="space-y-5">
      <Card
        title={t("Survey results")}
        action={
          <button
            type="button"
            onClick={() => downloadLocked("/survey/responses.csv", "survey_responses.csv")}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            ⬇ CSV
          </button>
        }
      >
        <SurveyPanel />
      </Card>
      <Card title={t("Each response")}>
        <ResponsesList />
      </Card>
    </div>
  );
}

function ExportPage() {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function download() {
    setBusy(true);
    setError(null);
    try {
      await downloadLocked("/trial/export.zip", "trial-export.zip");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title={t("Export trial data")}>
      <p className="text-sm text-slate-600">
        {t("Everything the trial produced, in one file, straight to this computer. Download it before destroying the rented box — its disk goes with it.")}
      </p>
      <button
        type="button"
        onClick={download}
        disabled={busy}
        className="mt-4 rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-bold text-white hover:bg-teal-700 disabled:bg-slate-300"
      >
        {busy ? t("Preparing…") : t("⬇ Download everything (.zip)")}
      </button>
      {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
      <table className="mt-5 w-full text-sm">
        <tbody className="text-slate-600">
          {[
            ["readers.csv", t("One row per room: name, when they joined, how much they did.")],
            ["survey_responses.csv", t("One row per questionnaire; opens in Excel with Vietnamese intact.")],
            ["questions.csv", t("The text of every Q column, so the answers stay readable.")],
            ["corrections.csv", t("Every grade a clinician changed, with their room.")],
            ["spine.db", t("A copy of the whole database, for anything the CSVs miss.")],
          ].map(([file, what]) => (
            <tr key={file} className="border-t border-slate-100">
              <td className="w-48 py-1.5 font-mono text-xs text-slate-800">{file}</td>
              <td className="py-1.5">{what}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-4 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">
        {t("Images clinicians uploaded are not in the zip — they can be hundreds of MB. Copy them off the box separately; see DEPLOY_VAST.md.")}
      </p>
    </Card>
  );
}

const NAV: [string, string][] = [
  ["", "Clinician rooms"],
  ["survey", "Survey results"],
  ["feedback", "Feedback & re-training"],
  ["models", "Model versions"],
  ["export", "Export trial data"],
];

export default function AdminHub() {
  const { t } = useT();
  const [gate, setGate] = useState<Gate>("checking");

  useEffect(() => {
    getAdminStatus()
      .then(async ({ locked }) => {
        if (!locked) return setGate("open");
        const key = readAdminKey();
        if (!key) return setGate("locked");
        try {
          await adminLogin(key);
          setGate("open");
        } catch {
          writeAdminKey(null);
          setGate("locked");
        }
      })
      .catch(() => setGate("locked"));
  }, []);

  if (gate === "checking") return null;
  if (gate === "locked") return <LoginCard onOpen={() => setGate("open")} />;

  return (
    <div className="min-h-screen">
      <header className="bg-slate-800 shadow-md">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-6 py-3">
          <Link
            to="/"
            className="rounded-lg bg-white/10 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-white/20"
          >
            {t("← Home")}
          </Link>
          <span className="text-sm font-bold text-white">{t("Admin")}</span>
          <nav className="flex flex-wrap gap-1">
            {NAV.map(([path, label]) => (
              <NavLink
                key={path}
                to={`/admin${path ? `/${path}` : ""}`}
                end={path === ""}
                className={({ isActive }) =>
                  "rounded-md px-3 py-1.5 text-xs font-medium transition " +
                  (isActive ? "bg-white text-slate-800" : "text-slate-300 hover:bg-white/10 hover:text-white")
                }
              >
                {t(label)}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <LangToggle />
            <button
              type="button"
              onClick={() => {
                writeAdminKey(null);
                setGate("locked");
              }}
              className="rounded-md border border-slate-600 px-2.5 py-1 text-xs text-slate-300 hover:text-white"
            >
              {t("Lock")}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">
        <Routes>
          <Route index element={<RoomsPage />} />
          <Route path="survey" element={<SurveyPage />} />
          <Route path="feedback" element={<Admin embedded />} />
          <Route path="models" element={<ModelVersions embedded />} />
          <Route path="export" element={<ExportPage />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </main>
    </div>
  );
}
