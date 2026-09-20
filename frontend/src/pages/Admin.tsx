import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getCorrectionBatches,
  getCorrections,
  getModelVersions,
  type BatchOut,
  type CorrectionOut,
  type CorrectionQueue,
} from "../lib/api";

/**
 * The operator's window on the first half of the feedback loop.
 *
 * A doctor corrects grades in the viewer; the corrections queue; sending them
 * seals a batch; **an engineer then runs re-training from a terminal**; the
 * checkpoint that produces appears on `/models` for a person to approve.
 *
 * Nothing on this page starts training, and nothing here should ever look as
 * if it might. The gap between "a batch is sealed" and "a new model exists" is
 * bridged by a human running two commands, and that gap is the claim the
 * thesis makes about this app: a correction made on one patient can never
 * quietly change what the next patient is graded by. So the page shows the
 * commands rather than a button — that is the honest way to expose re-training
 * from a screen that cannot perform it.
 *
 * It is a sibling of `ModelVersions.tsx`, which owns the second half (review
 * and activation). The two link to each other instead of repeating each other.
 */

/** How many rows `GET /corrections` will return at most (server-side cap). */
const ROW_CAP = 200;

/** Where an operator would put the dataset a batch rebuilds into. */
const DATASET_DIR = "data/finetune";

/**
 * The frozen held-out set, inside this repo. 200 rows, checksum-locked at
 * `backend/data/holdout_frozen/MANIFEST.json`.
 */
const HOLDOUT_DIR = "data/holdout_frozen";

/**
 * The replay set of original discs is NOT in this app: it is `rsna_preprocessed`
 * from the research repo, ~8.2 GB, and its absolute path differs per machine.
 * Deliberately a visible placeholder rather than an invented path.
 */
const REPLAY_DIR_PLACEHOLDER = "<PATH-TO>/rsna_preprocessed";

/**
 * The three conditions the fine-tuned grading model has heads for.
 *
 * `app/feedback/build_dataset.py` maps a corrected condition back to one of
 * these columns; a correction on any of the other eight conditions is logged
 * and batched but skipped when the dataset is built, because those grades come
 * from the vendored upstream SpineNet, which this loop does not re-train.
 */
const TRAINABLE_CONDITIONS = new Set([
  "canal_stenosis",
  "left_foraminal",
  "right_foraminal",
]);

const CONDITION_LABELS: Record<string, string> = {
  canal_stenosis: "Canal stenosis",
  left_foraminal: "Left foraminal",
  right_foraminal: "Right foraminal",
  pfirrmann: "Pfirrmann",
  disc_narrowing: "Disc narrowing",
  spondylolisthesis: "Spondylolisthesis",
  upper_endplate_defect: "Upper endplate defect",
  lower_endplate_defect: "Lower endplate defect",
  upper_marrow: "Upper marrow",
  lower_marrow: "Lower marrow",
  disc_herniation: "Disc herniation",
};

function conditionLabel(condition: string): string {
  return (
    CONDITION_LABELS[condition] ??
    condition.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
}

/** `"L4-L5/canal_stenosis"` -> its two halves, tolerating a malformed field. */
function splitField(field: string): { level: string; condition: string } {
  const slash = field.indexOf("/");
  if (slash < 0) return { level: "—", condition: field };
  return {
    level: field.slice(0, slash),
    condition: field.slice(slash + 1),
  };
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  // The backend stamps naive UTC; the browser would read a bare timestamp as
  // local time and silently shift it, so mark it as UTC before parsing.
  const date = new Date(/[Z+]|-\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/** Copy-to-clipboard that says whether it worked, because often it does not. */
function CopyButton({
  value,
  label = "Copy",
  className = "",
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");

  async function copy() {
    try {
      // `navigator.clipboard` is undefined on a page served over plain http
      // from anything but localhost, which is exactly how this app is reached
      // through an SSH tunnel — so the failure has to be visible, not silent.
      if (!navigator.clipboard) throw new Error("no clipboard API");
      await navigator.clipboard.writeText(value);
      setState("done");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 2000);
  }

  return (
    <button
      type="button"
      onClick={copy}
      title={state === "failed" ? "Select the text and copy it manually" : value}
      className={`rounded-md border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50 ${className}`}
    >
      {state === "done"
        ? "Copied"
        : state === "failed"
          ? "Copy failed"
          : label}
    </button>
  );
}

function StatTile({
  value,
  label,
  note,
  tone,
}: {
  value: number | string;
  label: string;
  note: string;
  tone: "queue" | "sent" | "batch";
}) {
  const cls = {
    queue: "text-indigo-600",
    sent: "text-slate-800",
    batch: "text-teal-600",
  }[tone];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className={`text-2xl font-bold tabular-nums ${cls}`}>{value}</div>
      <div className="text-xs font-semibold text-slate-700">{label}</div>
      <div className="mt-1 text-[11px] leading-snug text-slate-500">{note}</div>
    </div>
  );
}

/** One correction, as a table row. */
function CorrectionRow({ row }: { row: CorrectionOut }) {
  const { level, condition } = splitField(row.field);
  const trainable = TRAINABLE_CONDITIONS.has(condition);
  return (
    <tr className="border-t border-slate-200 align-top">
      <td className="py-1.5 pr-3">
        <Link
          to={`/viewer/${row.study_id}`}
          className="font-mono text-[11px] text-indigo-600 hover:underline"
        >
          {row.study_id}
        </Link>
      </td>
      <td className="py-1.5 pr-3 font-mono text-[11px] text-slate-700">
        {level}
      </td>
      <td className="py-1.5 pr-3 text-slate-700">
        {conditionLabel(condition)}
        {!trainable && (
          <span
            title="Graded by the vendored upstream SpineNet, which this loop does not re-train — build_dataset skips it."
            className="ml-1.5 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500"
          >
            not re-trained
          </span>
        )}
      </td>
      <td className="py-1.5 pr-3 whitespace-nowrap text-slate-500">
        {row.old ?? "—"}{" "}
        <span className="text-slate-400">→</span>{" "}
        <span className="font-semibold text-slate-800">{row.new ?? "—"}</span>
      </td>
      <td className="py-1.5 whitespace-nowrap text-right text-[11px] text-slate-500">
        {formatDate(row.at)}
      </td>
    </tr>
  );
}

function CorrectionTable({ rows }: { rows: CorrectionOut[] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-slate-500">
          <th className="pb-1 pr-3 text-left font-medium">Study</th>
          <th className="pb-1 pr-3 text-left font-medium">Level</th>
          <th className="pb-1 pr-3 text-left font-medium">Condition</th>
          <th className="pb-1 pr-3 text-left font-medium">Changed</th>
          <th className="pb-1 text-right font-medium">Corrected</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <CorrectionRow key={row.id} row={row} />
        ))}
      </tbody>
    </table>
  );
}

/**
 * Where this batch stands in the loop, drawn so the missing step is visible.
 *
 * The re-training step is a real part of the flow and belongs in the sequence,
 * but the app does not perform it: an engineer runs two commands in a
 * terminal. So it is drawn the way the thesis's architecture figure draws
 * anything not built into the software — dashed rather than solid — and its
 * button is disabled, labelled, and says in words where the step actually
 * happens. A button that looked live and did nothing would be the single
 * dishonest thing on a screen whose whole subject is that no model changes
 * without a person deciding, and a demo that presses it would find that out.
 */
function LoopSteps() {
  return (
    <div className="mt-4 flex flex-wrap items-stretch gap-2">
      <div className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
        <div className="text-[11px] font-semibold text-slate-700">
          1 · Batch sealed
        </div>
        <div className="mt-0.5 text-[11px] text-emerald-700">
          ✓ Done — in the app
        </div>
      </div>

      <div className="flex items-center text-slate-300">→</div>

      <div className="flex-1 rounded-lg border-2 border-dashed border-slate-300 bg-white px-3 py-2">
        <div className="text-[11px] font-semibold text-slate-700">
          2 · Re-train
        </div>
        <button
          type="button"
          disabled
          aria-disabled="true"
          title="Re-training is not run by this app. Copy the commands below and run them in a terminal."
          className="mt-1 w-full cursor-not-allowed rounded-md border border-dashed border-slate-300 bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-400"
        >
          Run re-training
        </button>
        <div className="mt-1 text-[11px] leading-snug text-slate-500">
          Not wired up. This step runs from a terminal — the commands are
          below.
        </div>
      </div>

      <div className="flex items-center text-slate-300">→</div>

      <div className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
        <div className="text-[11px] font-semibold text-slate-700">
          3 · A person approves
        </div>
        <Link
          to="/models"
          className="mt-0.5 inline-block text-[11px] font-medium text-indigo-600 hover:underline"
        >
          Model versions →
        </Link>
        <div className="mt-0.5 text-[11px] text-slate-500">
          In the app, once a checkpoint exists.
        </div>
      </div>
    </div>
  );
}

/** A shell block an operator is meant to run in a terminal, with a copy button. */
function Commands({ title, code }: { title: string; code: string }) {
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-slate-600">
          {title}
        </span>
        <CopyButton value={code} label="Copy commands" />
      </div>
      <pre className="mt-1 overflow-x-auto rounded-md bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">
        {code}
      </pre>
    </div>
  );
}

/**
 * The two commands that turn one sealed batch into a candidate checkpoint.
 *
 * Written out in full, with the batch id already substituted, because the
 * batch id is the only thing that makes a past training run reproducible.
 */
function retrainCommands(batchId: string, activeCheckpoint: string): string {
  const out = `${DATASET_DIR}/${batchId}`;
  return [
    "cd backend",
    "",
    "# 1 · Rebuild exactly the corrections this batch holds",
    "python -m app.feedback.build_dataset \\",
    `    --out-dir ${out} \\`,
    `    --batch-id ${batchId}`,
    "",
    "# 2 · Head-only fine-tune, scored on the frozen held-out set.",
    "#     Keeps the new checkpoint only if held-out macro-F1 improves.",
    "python -m app.feedback.retrain_head \\",
    `    --checkpoint models/weights/${activeCheckpoint} \\`,
    `    --dataset-dir ${out} \\`,
    `    --holdout-dir ${HOLDOUT_DIR} \\`,
    `    --replay-dir ${REPLAY_DIR_PLACEHOLDER} \\`,
    `    --out-checkpoint models/weights/${batchId}.pth`,
  ].join("\n");
}

function BatchCard({
  batch,
  rows,
  activeCheckpoint,
}: {
  batch: BatchOut;
  /** The rows of this batch the server actually returned (may be partial). */
  rows: CorrectionOut[];
  activeCheckpoint: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <article className="mb-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-slate-800">
          {batch.batch_id}
        </span>
        <CopyButton value={batch.batch_id} label="Copy id" />
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Sealed {formatDate(batch.sealed_at)} · {batch.corrections} correction
        {batch.corrections === 1 ? "" : "s"} from {batch.studies.length}{" "}
        {batch.studies.length === 1 ? "study" : "studies"}
      </p>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {batch.studies.map((studyId) => (
          <Link
            key={studyId}
            to={`/viewer/${studyId}`}
            className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-600 transition hover:bg-slate-200"
          >
            {studyId}
          </Link>
        ))}
      </div>

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mt-3 text-xs font-medium text-indigo-600 hover:underline"
      >
        {open ? "Hide the corrections" : "Show the corrections"}
      </button>

      {open && (
        <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-3">
          {rows.length === 0 ? (
            <p className="text-xs text-slate-500">
              The rows of this batch were not among the most recent {ROW_CAP}{" "}
              the server returns, so they are not listed here. The batch id
              above still rebuilds them exactly.
            </p>
          ) : (
            <>
              <CorrectionTable rows={rows} />
              {rows.length < batch.corrections && (
                <p className="mt-2 text-[11px] text-amber-700">
                  Showing {rows.length} of {batch.corrections} — the server
                  returns at most {ROW_CAP} rows.
                </p>
              )}
            </>
          )}
        </div>
      )}

      <LoopSteps />

      <Commands
        title="Step 2, in full — run these in a terminal"
        code={retrainCommands(batch.batch_id, activeCheckpoint)}
      />
    </article>
  );
}

export default function Admin() {
  const [queue, setQueue] = useState<CorrectionQueue | null>(null);
  const [sent, setSent] = useState<CorrectionOut[]>([]);
  const [batches, setBatches] = useState<BatchOut[] | null>(null);
  /** True when the batch list had to be rebuilt from rows, so it may be partial. */
  const [batchesDerived, setBatchesDerived] = useState(false);
  const [activeCheckpoint, setActiveCheckpoint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    // The counts are global; `status` only narrows which rows come back. Asking
    // for the newest 200 rows overall could return 200 sent ones and hide a
    // waiting correction, which is the one thing this screen must not do.
    Promise.all([
      getCorrections(ROW_CAP, "pending"),
      getCorrections(ROW_CAP, "submitted").catch(() => null),
      getCorrectionBatches().catch(() => null),
    ])
      .then(([pendingQueue, submittedQueue, batchList]) => {
        // A backend that predates `status` ignores it and returns a mixed
        // list, so filter here regardless of what was asked for.
        setQueue({
          ...pendingQueue,
          recent: pendingQueue.recent.filter((r) => r.submitted_at === null),
        });

        const sentRows = (submittedQueue?.recent ?? []).filter(
          (r) => r.submitted_at !== null,
        );
        setSent(sentRows);

        if (batchList) {
          setBatches(batchList);
          setBatchesDerived(false);
        } else {
          // Older backend without /corrections/batches: rebuild what we can
          // from the rows we do have, and say that it may be incomplete.
          setBatches(groupIntoBatches(sentRows));
          setBatchesDerived(true);
        }
        setError(null);
      })
      .catch((err: unknown) => {
        setQueue(null);
        setBatches(null);
        setError(err instanceof Error ? err.message : String(err));
      });

    getModelVersions()
      .then((versions) =>
        setActiveCheckpoint(versions.find((v) => v.is_active)?.name ?? null),
      )
      .catch(() => setActiveCheckpoint(null));
  }, []);

  useEffect(load, [load]);

  const checkpointForCommands = activeCheckpoint ?? "phase2_cbam.pth";
  const rowsByBatch = new Map<string, CorrectionOut[]>();
  for (const row of sent) {
    if (!row.batch_id) continue;
    const list = rowsByBatch.get(row.batch_id);
    if (list) list.push(row);
    else rowsByBatch.set(row.batch_id, [row]);
  }

  const pendingRows = queue?.recent ?? [];
  const pendingStudies = new Set(pendingRows.map((r) => r.study_id));

  return (
    <div className="min-h-screen">
      {/* Brand header, same as the worklist, the viewer and /models */}
      <header className="bg-gradient-to-r from-teal-600 to-cyan-500 shadow-md">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-6 py-3.5">
          <Link
            to="/"
            className="rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium text-white backdrop-blur transition hover:bg-white/25"
          >
            ← Worklist
          </Link>
          <div className="leading-tight text-white">
            <div className="text-sm font-bold">Feedback operations</div>
            <div className="text-xs text-teal-50/90">
              What doctors corrected, and what went out in which batch
            </div>
          </div>
          <Link
            to="/models"
            className="ml-auto rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium text-white backdrop-blur transition hover:bg-white/25"
          >
            Model versions →
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        <p className="mb-4 text-[11px] leading-relaxed text-slate-400">
          Operator view. There is no access control on this page — anyone who
          can open the app can open it, and the API answers the same requests
          directly. That is a deliberate choice for a demo, not a security
          boundary.
        </p>

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </div>
        )}

        {/* The three numbers this whole screen is about ------------------- */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatTile
            tone="queue"
            value={queue?.pending ?? "—"}
            label="Waiting to be sent"
            note="Saved by a doctor, not yet handed over. Not training material yet."
          />
          <StatTile
            tone="sent"
            value={queue?.submitted ?? "—"}
            label="Sent so far"
            note="Sealed into a batch and available to re-training."
          />
          <StatTile
            tone="batch"
            value={queue?.batches ?? "—"}
            label="Batches sealed"
            note="One per press of “Send corrections”, whoever pressed it."
          />
        </div>

        {/* The queue ------------------------------------------------------ */}
        <section className="mt-6">
          <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-indigo-500 to-violet-500" />
            The queue
          </h2>

          <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-relaxed text-amber-900">
            <p className="font-semibold">
              Sending corrections is app-wide, not per-study.
            </p>
            <p className="mt-1">
              The button in a patient's viewer hands over{" "}
              <strong>every correction waiting anywhere in the app</strong>,
              from every patient, and seals them into one batch — the counts
              beside it are global too, even though it sits inside one study's
              screen. That is correct behaviour rather than a bug: a batch from
              a single study would be a handful of discs, far too few to
              fine-tune on. It is worth knowing before you press it, which is
              why this page lists the whole queue in one place.
            </p>
            {pendingStudies.size > 1 && (
              <p className="mt-1 font-semibold">
                Right now the queue spans {pendingStudies.size} studies, so the
                next send seals all of them together.
              </p>
            )}
          </div>

          {queue === null ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : pendingRows.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm shadow-sm">
              <p className="font-medium text-slate-700">
                Nothing is waiting to be sent.
              </p>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                This is the normal resting state. When a doctor changes a grade
                in the viewer and presses “Save corrections”, one row appears
                here per changed grade — the study, the disc level, the
                condition, the old value, the new value and the time. Rows stay
                here, unused, until someone presses “Send corrections” in a
                viewer; that seals them into a batch, which then shows up below.
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <CorrectionTable rows={pendingRows} />
              {queue.pending > pendingRows.length && (
                <p className="mt-2 text-[11px] text-amber-700">
                  Showing the {pendingRows.length} most recent of{" "}
                  {queue.pending} — the server returns at most {ROW_CAP} rows.
                </p>
              )}
              <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                None of these has reached the model. They become training
                material only once someone sends them, which is done from a
                viewer, not from here.
              </p>
            </div>
          )}
        </section>

        {/* Batches -------------------------------------------------------- */}
        <section className="mt-6">
          <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
            Batches sent to re-training
          </h2>

          {batchesDerived && (
            <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
              This backend does not serve <code>/corrections/batches</code>, so
              the list below was rebuilt from the most recent {ROW_CAP}{" "}
              corrections and may be missing older batches.
            </p>
          )}

          {batches === null ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : batches.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm shadow-sm">
              <p className="font-medium text-slate-700">
                No batch has been sealed yet.
              </p>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                A batch appears here the moment a doctor sends the queue. Each
                one shows its id, when it was sealed, how many corrections it
                holds, which studies they came from, and the two commands that
                rebuild and re-train from exactly those corrections.
              </p>
            </div>
          ) : (
            batches.map((batch) => (
              <BatchCard
                key={batch.batch_id}
                batch={batch}
                rows={rowsByBatch.get(batch.batch_id) ?? []}
                activeCheckpoint={checkpointForCommands}
              />
            ))
          )}
        </section>

        {/* What re-training needs, and what this app has ------------------- */}
        <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-slate-400 to-slate-500" />
            Before running those commands
          </h2>

          <p className="text-xs leading-relaxed text-slate-600">
            The app cannot run re-training, and the commands above are not a
            button in disguise: they are run by an engineer, on a machine that
            has the training data. Two of the three things they need do not live
            in this repo in the same way.
          </p>

          <dl className="mt-3 space-y-3 text-xs leading-relaxed">
            <div>
              <dt className="font-semibold text-slate-700">
                The held-out set — in this app
              </dt>
              <dd className="text-slate-600">
                <code className="rounded bg-slate-100 px-1">
                  backend/{HOLDOUT_DIR}
                </code>{" "}
                holds 200 rows frozen before any correction was collected, with
                a checksum in its <code>MANIFEST.json</code>. It is what the
                before/after numbers on{" "}
                <Link to="/models" className="text-indigo-600 hover:underline">
                  Model versions
                </Link>{" "}
                are measured on. Re-freezing it would invalidate every
                comparison ever made against it — verify rather than rebuild:
                <br />
                <code className="mt-1 inline-block rounded bg-slate-100 px-1">
                  python -m app.feedback.freeze_holdout --verify {HOLDOUT_DIR}
                </code>
              </dd>
            </div>

            <div>
              <dt className="font-semibold text-slate-700">
                The replay set — not in this app
              </dt>
              <dd className="text-slate-600">
                <code className="rounded bg-slate-100 px-1">
                  --replay-dir
                </code>{" "}
                wants about 200 <em>original</em> discs mixed in alongside the
                corrections, so the heads stay anchored to the distribution the
                deployed checkpoint learned; training on a few dozen corrections
                alone is the standard way to make a model forget. Those discs
                are the preprocessed RSNA set (
                <code className="rounded bg-slate-100 px-1">
                  rsna_preprocessed
                </code>
                , ~8.2 GB) produced by the research repo. It is not part of this
                application and its path differs per machine, which is why the
                commands above carry{" "}
                <code className="rounded bg-slate-100 px-1">
                  {REPLAY_DIR_PLACEHOLDER}
                </code>{" "}
                rather than a path that might not exist. Substitute your copy.
              </dd>
            </div>

            <div>
              <dt className="font-semibold text-slate-700">
                Only three conditions are re-trained
              </dt>
              <dd className="text-slate-600">
                The loop fine-tunes canal stenosis and left/right foraminal
                narrowing — the heads of the app's own model. Corrections to the
                other eight conditions are recorded and batched, but they come
                from the vendored upstream SpineNet, so{" "}
                <code className="rounded bg-slate-100 px-1">build_dataset</code>{" "}
                skips them and prints them as skipped rows. They are marked{" "}
                <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
                  not re-trained
                </span>{" "}
                in the tables above.
              </dd>
            </div>
          </dl>

          <p className="mt-4 rounded-md bg-slate-50 px-2.5 py-2 text-xs leading-relaxed text-slate-500">
            There is no automatic trigger anywhere in this app: sealing a batch
            does not start a training run, and a finished training run does not
            put itself into service. A person runs the commands, and another
            person reads the held-out numbers on{" "}
            <Link to="/models" className="text-indigo-600 hover:underline">
              Model versions
            </Link>{" "}
            and decides. Both gaps are deliberate — they are what stops a
            correction made on one patient from changing what the next patient
            is graded by. The dashed step on each batch above is the first of
            them, drawn the way this project draws every part of the flow that
            is not built into the software.
          </p>
        </section>
      </main>
    </div>
  );
}

/** Fallback for a backend without `/corrections/batches`: group rows by id. */
function groupIntoBatches(rows: CorrectionOut[]): BatchOut[] {
  const batches: BatchOut[] = [];
  const byId = new Map<string, BatchOut>();
  for (const row of rows) {
    if (!row.batch_id) continue;
    const existing = byId.get(row.batch_id);
    if (existing) {
      existing.corrections += 1;
      if (!existing.studies.includes(row.study_id)) {
        existing.studies.push(row.study_id);
      }
      continue;
    }
    const batch: BatchOut = {
      batch_id: row.batch_id,
      sealed_at: row.submitted_at,
      corrections: 1,
      studies: [row.study_id],
    };
    byId.set(row.batch_id, batch);
    batches.push(batch);
  }
  return batches.sort((a, b) =>
    (a.sealed_at ?? "") < (b.sealed_at ?? "") ? 1 : -1,
  );
}
