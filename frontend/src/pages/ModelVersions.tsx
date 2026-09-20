import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  activateModel,
  getModelActivations,
  getModelVersions,
  revertModel,
  type ActivationOut,
  type CheckpointOut,
} from "../lib/api";

/**
 * The human gate on the feedback loop.
 *
 * Corrections are queued, re-training runs offline, and the checkpoint it
 * produces does nothing until a person reads its held-out numbers here and
 * deliberately puts it into service. This screen is that step, so it is
 * written to read as a decision with consequences: activation is confirmed in
 * two moves, the confirmation spells out what changes, and reverting to the
 * shipped baseline is always one click away.
 *
 * It lives on its own route rather than inside the Viewer because the choice
 * is app-wide: it governs every study graded from now on, not the study a
 * doctor happens to have open.
 */

/** "243 MB" — a checkpoint is always megabytes; a byte count reads as noise. */
function formatSize(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  // A sub-megabyte ".pth" is not a real checkpoint; rounding it to "0 MB"
  // would hide that, so keep the small units honest.
  if (mb >= 1) return `${mb.toFixed(0)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** For timestamps the backend took from the filesystem, i.e. already local. */
function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/**
 * For timestamps the database stamped, which are naive UTC.
 *
 * A bare `2026-09-20T17:42:32` is read by the browser as local time, so the
 * activation log would claim a decision was made seven hours before or after
 * it was — exactly the kind of quiet inaccuracy an audit trail cannot afford.
 * Marking it as UTC before parsing is the same thing the operator page does.
 */
function formatUtcDate(iso: string): string {
  const date = new Date(/[Z+]|-\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

// Metric keys the retraining script writes into the sidecar JSON
// (`app/feedback/retrain_head.py`). The headline three come first; per-head
// numbers are folded away because nobody reads 7 rows to make one decision.
const HEADLINE_METRICS = ["macro_f1", "severe_f1", "mean_acc"];

const METRIC_LABELS: Record<string, string> = {
  macro_f1: "Macro F1",
  severe_f1: "Severe F1",
  mean_acc: "Mean accuracy",
  loss: "Loss (lower is better)",
  acc_spinal_canal: "Accuracy · Canal",
  acc_left_foraminal: "Accuracy · L. foraminal",
  acc_right_foraminal: "Accuracy · R. foraminal",
  f1_spinal_canal: "F1 · Canal",
  f1_left_foraminal: "F1 · L. foraminal",
  f1_right_foraminal: "F1 · R. foraminal",
};

/** Lower is better for loss; everything else the script reports is a score. */
const LOWER_IS_BETTER = new Set(["loss"]);

function metricLabel(key: string): string {
  return (
    METRIC_LABELS[key] ??
    key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
}

interface MetricComparison {
  key: string;
  label: string;
  before: number;
  after: number;
  delta: number;
  /** null when the two numbers are equal, so no colour is claimed. */
  improved: boolean | null;
}

function numberMap(value: unknown): Record<string, number> {
  if (typeof value !== "object" || value === null) return {};
  const out: Record<string, number> = {};
  for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
    if (typeof entry === "number" && Number.isFinite(entry)) out[key] = entry;
  }
  return out;
}

/**
 * Pair up the sidecar's `before`/`after` blocks into comparable rows.
 *
 * Only keys present in both are shown: a number with nothing to compare it
 * against cannot support the decision this screen exists for.
 */
function compareMetrics(metrics: Record<string, unknown> | null): {
  headline: MetricComparison[];
  perHead: MetricComparison[];
} {
  const before = numberMap(metrics?.before);
  const after = numberMap(metrics?.after);

  const rows: MetricComparison[] = Object.keys(after)
    .filter((key) => key in before)
    .map((key) => {
      const delta = after[key] - before[key];
      const better = LOWER_IS_BETTER.has(key) ? -delta : delta;
      return {
        key,
        label: metricLabel(key),
        before: before[key],
        after: after[key],
        delta,
        improved: better === 0 ? null : better > 0,
      };
    });

  const headline = HEADLINE_METRICS.map((key) =>
    rows.find((r) => r.key === key),
  ).filter((r): r is MetricComparison => r != null);
  const perHead = rows.filter((r) => !HEADLINE_METRICS.includes(r.key));
  return { headline, perHead };
}

function formatDelta(row: MetricComparison): string {
  const sign = row.delta > 0 ? "+" : row.delta < 0 ? "−" : "±";
  return `${sign}${Math.abs(row.delta).toFixed(3)}`;
}

function deltaClass(improved: boolean | null): string {
  if (improved === null) return "text-slate-400";
  return improved ? "text-emerald-600" : "text-rose-600";
}

function MetricTable({ rows }: { rows: MetricComparison[] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-slate-500">
          <th className="py-1 text-left font-medium">Measure</th>
          {/* "Before" is the checkpoint this one was fine-tuned from, which is
              not necessarily the one in service — the caption below names it. */}
          <th className="py-1 text-right font-medium">Before</th>
          <th className="py-1 text-right font-medium">This candidate</th>
          <th className="py-1 text-right font-medium">Change</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} className="border-t border-slate-200">
            <td className="py-1 text-slate-700">{row.label}</td>
            <td className="py-1 text-right tabular-nums text-slate-500">
              {row.before.toFixed(3)}
            </td>
            <td className="py-1 text-right font-semibold tabular-nums text-slate-800">
              {row.after.toFixed(3)}
            </td>
            <td
              className={`py-1 text-right font-semibold tabular-nums ${deltaClass(row.improved)}`}
            >
              {formatDelta(row)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Whether a checkpoint carries a before/after pair worth reviewing. */
function hasMetrics(checkpoint: CheckpointOut): boolean {
  const { headline, perHead } = compareMetrics(checkpoint.metrics);
  return headline.length + perHead.length > 0;
}

/** The before/after numbers a candidate carries, or a plain note that it has none. */
function MetricsPanel({ checkpoint }: { checkpoint: CheckpointOut }) {
  const { headline, perHead } = compareMetrics(checkpoint.metrics);
  const meta = checkpoint.metrics ?? {};
  const trainedAt = typeof meta.trained_at === "string" ? meta.trained_at : null;
  const corrections =
    typeof meta.n_corrections === "number" ? meta.n_corrections : null;
  const baseCheckpoint =
    typeof meta.base_checkpoint === "string" ? meta.base_checkpoint : null;

  if (headline.length === 0 && perHead.length === 0) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        <strong>No evaluation numbers came with this checkpoint.</strong> The
        re-training script writes a{" "}
        <code className="rounded bg-amber-100 px-1">&lt;name&gt;.pth.json</code>{" "}
        sidecar holding its before/after scores on the frozen held-out set.
        Without it there is nothing to review, and activating would be a blind
        change.
      </div>
    );
  }

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="mb-2 text-xs font-semibold text-slate-700">
        Measured on the frozen held-out set
      </p>
      <MetricTable rows={headline} />
      {perHead.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs font-medium text-slate-500">
            Per-condition numbers
          </summary>
          <div className="mt-1">
            <MetricTable rows={perHead} />
          </div>
        </details>
      )}
      <p className="mt-2 text-[11px] leading-snug text-slate-500">
        These are held-out scores, not scores on the corrections the model was
        trained on. <strong>Before</strong> is{" "}
        {baseCheckpoint ? (
          <>the checkpoint it was fine-tuned from, {baseCheckpoint}</>
        ) : (
          <>the checkpoint it was fine-tuned from</>
        )}
        , measured on the same set.
        {corrections != null && (
          <>
            {" "}
            Trained on {corrections} correction
            {corrections === 1 ? "" : "s"}.
          </>
        )}
        {trainedAt && <> Produced {formatDate(trainedAt)}.</>}
      </p>
    </div>
  );
}

function Badge({
  tone,
  children,
}: {
  tone: "active" | "baseline" | "candidate";
  children: React.ReactNode;
}) {
  const cls = {
    active: "bg-teal-100 text-teal-700",
    baseline: "bg-slate-100 text-slate-600",
    candidate: "bg-indigo-100 text-indigo-700",
  }[tone];
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}
    >
      {children}
    </span>
  );
}

/**
 * Every recorded decision to change what grades patients, newest first.
 *
 * This sits next to "In service now" because it answers the question that
 * card raises and used to leave hanging: the page could say which checkpoint
 * is running, but nothing said who put it there or what it replaced. For a
 * tool whose whole claim is that the model changes only when a person decides,
 * an unrecorded decision is the same as no decision at all.
 *
 * Reverts appear here too, as decisions in their own right.
 */
function ActivationHistory({ entries }: { entries: ActivationOut[] | null }) {
  if (entries === null) {
    return <p className="mt-4 text-xs text-slate-500">Loading history…</p>;
  }

  if (entries.length === 0) {
    return (
      <p className="mt-4 border-t border-slate-100 pt-3 text-xs leading-relaxed text-slate-500">
        Nothing has been switched on this server yet — the checkpoint the app
        shipped with is still the one grading studies. Every activation and
        revert from here on is recorded below.
      </p>
    );
  }

  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      <h3 className="text-xs font-semibold text-slate-700">
        What has been put into service, and when
      </h3>
      <ol className="mt-2 space-y-2">
        {entries.map((entry) => (
          <li key={entry.id} className="flex gap-2.5 text-xs">
            <span
              className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                entry.action === "revert" ? "bg-slate-400" : "bg-teal-500"
              }`}
            />
            <div className="leading-relaxed">
              <span className="font-medium text-slate-700">
                {entry.action === "revert"
                  ? "Reverted to"
                  : "Put into service:"}
              </span>{" "}
              <span className="font-mono text-slate-800">
                {entry.checkpoint}
              </span>
              {entry.previous_checkpoint &&
                entry.previous_checkpoint !== entry.checkpoint && (
                  <>
                    {" "}
                    <span className="text-slate-500">replacing</span>{" "}
                    <span className="font-mono text-slate-600">
                      {entry.previous_checkpoint}
                    </span>
                  </>
                )}
              <div className="text-[11px] text-slate-500">
                {formatUtcDate(entry.at)} ·{" "}
                {/* No sign-in exists in this build, so the record is honest
                    about it rather than naming an invented user. */}
                {entry.actor ?? "unattributed (this build has no sign-in)"}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function ModelVersions() {
  const [checkpoints, setCheckpoints] = useState<CheckpointOut[] | null>(null);
  const [activations, setActivations] = useState<ActivationOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  /** Name of the checkpoint whose confirmation step is open ("" = revert). */
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(() => {
    getModelVersions()
      .then((list) => {
        setCheckpoints(list);
        setError(null);
      })
      .catch((err: unknown) => {
        setCheckpoints(null);
        setError(err instanceof Error ? err.message : String(err));
      });
    // The history is supporting evidence, not the page: a server too old to
    // have it still shows which checkpoint is in service.
    getModelActivations()
      .then(setActivations)
      .catch(() => setActivations([]));
  }, []);

  useEffect(load, [load]);

  async function handleActivate(name: string) {
    setBusy(true);
    setError(null);
    try {
      const info = await activateModel(name);
      setNote(
        `${info.name} is now in service. Studies graded from now on use it.`,
      );
      setConfirming(null);
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRevert() {
    setBusy(true);
    setError(null);
    try {
      const info = await revertModel();
      setNote(`Reverted to the baseline ${info.name}.`);
      setConfirming(null);
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const active = checkpoints?.find((c) => c.is_active) ?? null;
  const baseline = checkpoints?.find((c) => c.is_baseline) ?? null;
  // The baseline is never a "candidate": it is the validated fallback, and the
  // way back to it is the revert button, not an approval decision.
  const candidates =
    checkpoints?.filter((c) => !c.is_active && !c.is_baseline) ?? [];

  return (
    <div className="min-h-screen">
      {/* Brand header, same as the worklist and the viewer */}
      <header className="bg-gradient-to-r from-teal-600 to-cyan-500 shadow-md">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-6 py-3.5">
          <Link
            to="/"
            className="rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium text-white backdrop-blur transition hover:bg-white/25"
          >
            ← Worklist
          </Link>
          <div className="leading-tight text-white">
            <div className="text-sm font-bold">Model versions</div>
            <div className="text-xs text-teal-50/90">
              Which checkpoint grades new studies
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </div>
        )}
        {note && (
          <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700">
            {note}
          </div>
        )}

        {/* In service now ------------------------------------------------ */}
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
            In service now
          </h2>

          {checkpoints === null ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : active === null ? (
            <p className="text-sm text-slate-500">
              No checkpoint is on the server, so nothing can be graded.
            </p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-semibold text-slate-800">
                  {active.name}
                </span>
                <Badge tone="active">In service</Badge>
                {active.is_baseline && <Badge tone="baseline">Baseline</Badge>}
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {formatSize(active.size_bytes)} ·{" "}
                {formatDate(active.modified_at)}
              </p>
              <p className="mt-3 text-xs leading-relaxed text-slate-600">
                Every study graded from now on is graded by this checkpoint.
                Grades already saved are not re-computed, and a correction a
                doctor saves never changes the model on its own.
              </p>

              {!active.is_baseline && (
                <div className="mt-3">
                  {confirming === "" ? (
                    <div className="rounded-md border border-slate-300 bg-slate-50 p-3">
                      <p className="text-xs font-semibold text-slate-700">
                        Go back to the shipped baseline?
                      </p>
                      <p className="mt-1 text-xs text-slate-600">
                        {baseline ? (
                          <>
                            <span className="font-mono">{baseline.name}</span>{" "}
                            is the checkpoint the app was validated with.
                          </>
                        ) : (
                          <>The baseline is the checkpoint the app was validated with.</>
                        )}{" "}
                        Studies graded from now on would use it again.{" "}
                        {active?.name} stays on the server, so this is not a
                        one-way move either.
                      </p>
                      <div className="mt-2 flex gap-2">
                        <button
                          type="button"
                          onClick={handleRevert}
                          disabled={busy}
                          className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50"
                        >
                          {busy ? "Reverting…" : "Yes, revert to the baseline"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirming(null)}
                          disabled={busy}
                          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setNote(null);
                        setConfirming("");
                      }}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
                    >
                      ↩ Revert to baseline
                    </button>
                  )}
                </div>
              )}
            </>
          )}

          <ActivationHistory entries={activations} />
        </section>

        {/* Candidates ---------------------------------------------------- */}
        <section className="mt-6">
          <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-indigo-500 to-violet-500" />
            Waiting for review
          </h2>

          {checkpoints !== null && candidates.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-600 shadow-sm">
              <p className="font-medium text-slate-700">
                {active?.is_baseline === false
                  ? "Nothing more to review — every checkpoint on this server has been dealt with."
                  : "Nothing to review — the baseline is the only checkpoint on this server."}
              </p>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                {active?.is_baseline === false ? (
                  <>
                    The version in service was approved here. If it turns out to
                    grade worse in practice, revert to the baseline above.
                  </>
                ) : (
                  <>
                    No re-training run has produced a new version yet, so there
                    is no decision to make here. This is the normal state.
                  </>
                )}
              </p>
            </div>
          )}

          {candidates.map((checkpoint) => (
            <article
              key={checkpoint.name}
              className="mb-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-semibold text-slate-800">
                  {checkpoint.name}
                </span>
                <Badge tone="candidate">Candidate</Badge>
              </div>
              <p className="mt-1 mb-3 text-xs text-slate-500">
                {formatSize(checkpoint.size_bytes)} ·{" "}
                {formatDate(checkpoint.modified_at)}
              </p>

              <MetricsPanel checkpoint={checkpoint} />

              {confirming === checkpoint.name ? (
                <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3">
                  <p className="text-xs font-bold text-amber-900">
                    Put {checkpoint.name} into service?
                  </p>
                  <ul className="mt-2 space-y-1 text-xs leading-relaxed text-amber-800">
                    <li>
                      · It becomes the model that grades{" "}
                      <strong>every study graded from now on</strong>, for every
                      patient.
                    </li>
                    <li>· It takes effect on the next grading run.</li>
                    <li>
                      · Grades already saved are left exactly as they are.
                    </li>
                    <li>
                      · The baseline stays on the server, so you can revert at
                      any time.
                    </li>
                    {!hasMetrics(checkpoint) && (
                      <li className="font-semibold">
                        · Nothing measures what this changes — no held-out
                        numbers came with this checkpoint.
                      </li>
                    )}
                  </ul>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      onClick={() => handleActivate(checkpoint.name)}
                      disabled={busy}
                      className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-amber-700 disabled:opacity-50"
                    >
                      {busy
                        ? "Activating…"
                        : "Yes, grade future studies with this model"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirming(null)}
                      disabled={busy}
                      className="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-800 transition hover:bg-amber-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setNote(null);
                    setConfirming(checkpoint.name);
                  }}
                  // A checkpoint with no held-out numbers gets a quiet button:
                  // there is nothing here to approve it on, so the screen must
                  // not invite the click.
                  className={
                    hasMetrics(checkpoint)
                      ? "mt-3 rounded-lg bg-gradient-to-r from-indigo-600 to-violet-500 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:brightness-110"
                      : "mt-3 rounded-lg border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
                  }
                >
                  {hasMetrics(checkpoint)
                    ? "Review and activate…"
                    : "Activate without numbers…"}
                </button>
              )}
            </article>
          ))}
        </section>

        {/* How a version gets here --------------------------------------- */}
        <details
          className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
          open={checkpoints !== null && candidates.length === 0}
        >
          <summary className="flex cursor-pointer items-center gap-2 text-base font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-indigo-500 to-violet-500" />
            How a new version gets here
          </summary>
          <ol className="mt-3 space-y-2 text-xs leading-relaxed text-slate-600">
            <li>
              <strong className="text-slate-700">1 · A doctor corrects.</strong>{" "}
              A grade fixed in the viewer and saved is recorded as expert
              feedback. It does not touch the model.
            </li>
            <li>
              <strong className="text-slate-700">
                2 · The corrections are sent.
              </strong>{" "}
              Sending them from the viewer marks a batch as ready. It still does
              not touch the model.
            </li>
            <li>
              <strong className="text-slate-700">
                3 · Someone runs re-training on a batch.
              </strong>{" "}
              From{" "}
              <Link to="/admin" className="text-indigo-600 hover:underline">
                Feedback operations
              </Link>{" "}
              (or a terminal). It scores the result on a frozen held-out set and
              only keeps a checkpoint that improves. The new file lands beside
              the baseline, serving nothing.
            </li>
            <li>
              <strong className="text-slate-700">4 · Someone decides.</strong>{" "}
              The candidate appears above with its before/after numbers, and
              stays inert until a person activates it here.
            </li>
          </ol>
          <p className="mt-3 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs text-slate-500">
            The loop is deliberately not instant. If a correction made on one
            patient could change what the next patient is graded, the same scan
            would read differently from one hour to the next — which is not
            acceptable in a clinical tool.
          </p>
        </details>
      </main>
    </div>
  );
}
