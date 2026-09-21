import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  getCorrectionBatches,
  getCorrections,
  getJob,
  getModelVersions,
  getRetrainReadiness,
  getRetrainRuns,
  startBatchRetrain,
  type BatchOut,
  type CorrectionOut,
  type CorrectionQueue,
  type JobOut,
  type RetrainReadiness,
  type RetrainRunOut,
} from "../lib/api";

/**
 * The operator's window on the first half of the feedback loop.
 *
 * A doctor corrects grades in the viewer; the corrections queue; sending them
 * seals a batch; **someone runs re-training on that batch from here**; the
 * candidate checkpoint it produces appears on `/models` for a person to
 * approve.
 *
 * The button on this page starts a run. It does not break the claim the thesis
 * makes about this app, because the claim was never "there is no trigger" — it
 * is that a correction made on one patient cannot change what the next patient
 * is graded by until a person deliberately approves a new checkpoint. A run
 * produces a candidate file and a row in the run log; the model in service is
 * the one it was before. The gate is the approval step on `/models`, and this
 * page says so wherever it offers to start something.
 *
 * Two things this screen is careful to show rather than hide: the replay set
 * of original discs is 8.2 GB that lives in the research repo and is simply
 * absent on some machines (so a run is blocked, not silently weakened), and
 * head-only fine-tuning on CPU takes tens of minutes (so a run in progress is
 * loud, keeps its stage on screen, and survives leaving the page).
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
 * Shown only when the server has no path configured — otherwise the commands
 * carry the real one.
 */
const REPLAY_DIR_PLACEHOLDER = "<PATH-TO>/rsna_preprocessed";

/** How often a run in progress is polled, in ms. Runs last minutes. */
const POLL_MS = 3000;

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

/** "14 min 02 s" — a run is minutes, and rounding it to minutes hides drift. */
function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  if (minutes === 0) return `${rest} s`;
  return `${minutes} min ${String(rest).padStart(2, "0")} s`;
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

// --- Running one batch -----------------------------------------------------

interface RetrainParams {
  /**
   * What the run trains on.
   *
   * "all" is the default on purpose. A loop that only ever trains on the
   * newest batch lets earlier corrections decay — round two never sees round
   * one's edits in its training data, only inside the weights it starts from.
   * The replay discs do not cover that: they are original RSNA scans, so they
   * anchor the model to the original distribution, not to what the doctors
   * have said since.
   */
  scope: "all" | "batch";
  epochs: number;
  replay_size: number;
}

const DEFAULT_PARAMS: RetrainParams = {
  scope: "all",
  epochs: 5,
  replay_size: 200,
};

/** A live run, as the job reports it: stage, bar, elapsed, and reassurance. */
function RunningPanel({ job }: { job: JobOut }) {
  return (
    <div className="mt-1 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold text-indigo-800">
          Running · {formatDuration(job.elapsed_seconds)}
        </span>
        <span className="text-[11px] tabular-nums text-indigo-700">
          {job.percent}%
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-indigo-100">
        <div
          className="h-full rounded-full bg-indigo-500 transition-all"
          style={{ width: `${job.percent}%` }}
        />
      </div>
      <div className="mt-1 text-[11px] leading-snug text-indigo-900">
        {job.stage}
      </div>
      <div className="mt-1 text-[11px] leading-snug text-indigo-700/80">
        Head-only fine-tuning on CPU takes tens of minutes. You can leave this
        page — the run continues on the server and this panel finds it again.
      </div>
    </div>
  );
}

/**
 * The trigger for one batch, in whichever of its states applies.
 *
 * The replay-free variant is deliberately awkward: a separate, plainly
 * labelled button behind its own confirmation, never the thing that happens
 * when you press the ordinary one. Without ~200 original discs mixed in, a
 * few dozen corrections drag the heads wherever they point, which is a
 * different experiment rather than a slightly worse version of this one.
 */
function RetrainControl({
  batchId,
  readiness,
  job,
  jobBatchId,
  lastRun,
  starting,
  error,
  confirming,
  setConfirming,
  onStart,
}: {
  batchId: string;
  readiness: RetrainReadiness | null;
  job: JobOut | null;
  jobBatchId: string | null;
  lastRun: RetrainRunOut | null;
  starting: boolean;
  error: string | null;
  /** Owned by the parent: a confirmation widens the step it lives in. */
  confirming: null | "full" | "replayless";
  setConfirming: (next: null | "full" | "replayless") => void;
  onStart: (
    batchId: string,
    params: RetrainParams,
    withoutReplay: boolean,
  ) => void;
}) {
  const [params, setParams] = useState<RetrainParams>(DEFAULT_PARAMS);

  const isMine = jobBatchId === batchId && job !== null;
  if (isMine && job.status === "running") return <RunningPanel job={job} />;

  const busyElsewhere =
    readiness?.running_batch_id != null && readiness.running_batch_id !== batchId;
  const canRun = readiness?.can_run === true && !busyElsewhere;
  const canRunWithoutReplay =
    readiness?.can_run_without_replay === true && !busyElsewhere;

  const priorDuration =
    lastRun?.duration_seconds != null ? lastRun.duration_seconds : null;

  function start(withoutReplay: boolean) {
    setConfirming(null);
    onStart(batchId, params, withoutReplay);
  }

  if (confirming !== null) {
    const replayless = confirming === "replayless";
    return (
      <div
        className={`mt-1 rounded-md border p-2 ${
          replayless
            ? "border-amber-300 bg-amber-50"
            : "border-indigo-200 bg-indigo-50"
        }`}
      >
        <p
          className={`text-[11px] font-bold ${replayless ? "text-amber-900" : "text-indigo-900"}`}
        >
          {replayless
            ? "Run without the replay set?"
            : "Start a re-training run?"}
        </p>

        <fieldset className="mt-1.5 rounded border border-slate-200 bg-white/70 p-1.5">
          <legend className="px-1 text-[11px] font-semibold text-slate-600">
            What it trains on
          </legend>
          <label className="flex cursor-pointer gap-1.5 text-[11px] text-slate-700">
            <input
              type="radio"
              name={`scope-${batchId}`}
              checked={params.scope === "all"}
              onChange={() => setParams((p) => ({ ...p, scope: "all" }))}
              className="mt-0.5"
            />
            <span>
              <strong>All corrections sent so far</strong>
              {readiness != null && (
                <>
                  {" "}
                  — {readiness.cumulative_corrections} correction
                  {readiness.cumulative_corrections === 1 ? "" : "s"} across{" "}
                  {readiness.sealed_batches} batch
                  {readiness.sealed_batches === 1 ? "" : "es"}
                </>
              )}
              . Each round then has to satisfy everything the doctors have
              corrected to date, not only the newest batch. A grade corrected
              twice counts once — the latest edit wins, duplicates do not pile
              up.
            </span>
          </label>
          <label className="mt-1 flex cursor-pointer gap-1.5 text-[11px] text-slate-700">
            <input
              type="radio"
              name={`scope-${batchId}`}
              checked={params.scope === "batch"}
              onChange={() => setParams((p) => ({ ...p, scope: "batch" }))}
              className="mt-0.5"
            />
            <span>
              <strong>This batch only</strong> — exactly what{" "}
              <span className="font-mono">{batchId}</span> holds. Reproducible:
              the same batch id rebuilds the same data later.
            </span>
          </label>
          {params.scope === "all" && (
            <p className="mt-1 text-[11px] leading-snug text-slate-500">
              Two costs worth knowing: the cumulative set grows every round, so
              runs get slower and head-only fine-tuning stops being obviously
              the right method once it is large; and it enforces older
              corrections indefinitely, which entrenches one reader's judgement
              — agreement between readers on this task is only about κ=0.68, so
              corrections are not ground truth.
            </p>
          )}
        </fieldset>
        <ul
          className={`mt-1 space-y-0.5 text-[11px] leading-snug ${replayless ? "text-amber-800" : "text-indigo-900/90"}`}
        >
          <li>
            · It fine-tunes the heads of{" "}
            <span className="font-mono">
              {readiness?.base_checkpoint ?? "the checkpoint in service"}
            </span>{" "}
            on{" "}
            {params.scope === "all"
              ? "every correction sent so far"
              : "this batch"}{" "}
            and scores the result on the frozen held-out set.
          </li>
          <li>
            · A new checkpoint is written <strong>only</strong> if held-out
            macro-F1 improves. "No improvement, nothing saved" is a normal
            result.
          </li>
          <li>
            · Nothing is activated. What grades the next patient does not
            change until someone approves the candidate on{" "}
            <Link to="/models" className="underline">
              Model versions
            </Link>
            .
          </li>
          <li>
            · It runs on CPU and takes minutes, not seconds
            {priorDuration != null && (
              <> — the last run here took {formatDuration(priorDuration)}</>
            )}
            . Only one run at a time.
          </li>
          {replayless && (
            <li className="font-semibold">
              · Without the replay discs there is no guard against the model
              forgetting what it already knew. This is a weaker experiment, and
              the run log will record it as one.
            </li>
          )}
        </ul>

        <details className="mt-1.5">
          <summary className="cursor-pointer text-[11px] font-medium text-slate-600">
            Parameters
          </summary>
          <div className="mt-1 flex flex-wrap gap-3">
            <label className="text-[11px] text-slate-600">
              Epochs (max)
              <input
                type="number"
                min={1}
                max={20}
                value={params.epochs}
                onChange={(e) =>
                  setParams((p) => ({
                    ...p,
                    epochs: Number(e.target.value) || 1,
                  }))
                }
                className="ml-1 w-16 rounded border border-slate-300 px-1 py-0.5 text-[11px]"
              />
            </label>
            {!replayless && (
              <label className="text-[11px] text-slate-600">
                Replay discs
                <input
                  type="number"
                  min={0}
                  max={2000}
                  step={50}
                  value={params.replay_size}
                  onChange={(e) =>
                    setParams((p) => ({
                      ...p,
                      replay_size: Number(e.target.value) || 0,
                    }))
                  }
                  className="ml-1 w-20 rounded border border-slate-300 px-1 py-0.5 text-[11px]"
                />
              </label>
            )}
          </div>
          <p className="mt-1 text-[11px] leading-snug text-slate-500">
            Early stopping can end a run before the last epoch. More epochs and
            more replay discs both make the run longer, roughly in proportion.
          </p>
        </details>

        <div className="mt-2 flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => start(replayless)}
            disabled={starting}
            className={`rounded-md px-2.5 py-1 text-[11px] font-semibold text-white transition disabled:opacity-50 ${
              replayless
                ? "bg-amber-600 hover:bg-amber-700"
                : "bg-indigo-600 hover:bg-indigo-700"
            }`}
          >
            {starting
              ? "Starting…"
              : replayless
                ? "Yes, run without replay"
                : "Yes, start the run"}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(null)}
            className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 transition hover:bg-slate-50"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setConfirming("full")}
        disabled={!canRun || starting}
        title={
          canRun
            ? "Rebuild this batch and fine-tune the heads on it"
            : busyElsewhere
              ? `A run on ${readiness?.running_batch_id} is still going`
              : (readiness?.replay_blocker ??
                readiness?.blockers.join(" ") ??
                "Not ready")
        }
        className={
          canRun
            ? "w-full rounded-md bg-gradient-to-r from-indigo-600 to-violet-500 px-2 py-1 text-[11px] font-semibold text-white shadow-sm transition hover:brightness-110"
            : "w-full cursor-not-allowed rounded-md border border-slate-300 bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-400"
        }
      >
        Run re-training
      </button>

      {busyElsewhere && (
        <div className="mt-1 text-[11px] leading-snug text-slate-500">
          A run on{" "}
          <span className="font-mono">{readiness?.running_batch_id}</span> is
          still going. One at a time — a run uses the whole CPU.
        </div>
      )}

      {!busyElsewhere && !canRun && readiness && (
        <div className="mt-1 text-[11px] leading-snug text-amber-700">
          {readiness.blockers.length > 0
            ? readiness.blockers.join(" ")
            : readiness.replay_blocker}
        </div>
      )}

      {!busyElsewhere && !canRun && canRunWithoutReplay && (
        <button
          type="button"
          onClick={() => setConfirming("replayless")}
          className="mt-1 w-full rounded-md border border-amber-300 bg-white px-2 py-1 text-[11px] font-medium text-amber-800 transition hover:bg-amber-50"
        >
          Run without the replay set (weaker)…
        </button>
      )}

      {isMine && job.status === "error" && (
        <div className="mt-1 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700">
          The run failed: {job.error}
        </div>
      )}
      {isMine && job.status === "done" && lastRun?.status === "done" && (
        <div
          className={`mt-1 rounded-md border px-2 py-1 text-[11px] ${
            lastRun.improved
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-slate-200 bg-slate-50 text-slate-600"
          }`}
        >
          {lastRun.improved ? (
            <>
              Finished in {formatDuration(lastRun.duration_seconds ?? 0)} —
              candidate{" "}
              <span className="font-mono">{lastRun.checkpoint_name}</span> is
              waiting on{" "}
              <Link to="/models" className="underline">
                Model versions
              </Link>
              .
            </>
          ) : (
            <>
              Finished in {formatDuration(lastRun.duration_seconds ?? 0)} — no
              held-out improvement, so nothing was saved. The model in service
              is unchanged.
            </>
          )}
        </div>
      )}
      {error && (
        <div className="mt-1 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700">
          {error}
        </div>
      )}
    </div>
  );
}

/**
 * Where this batch stands in the loop.
 *
 * All three steps are solid now: the middle one is a button on this page, and
 * the one after it is a person on `/models`. The step that is drawn as a
 * decision rather than an action is step 3, because that is the one the whole
 * design rests on — a run produces a candidate and nothing else changes.
 */
function LoopSteps({
  batchId,
  readiness,
  job,
  jobBatchId,
  lastRun,
  starting,
  error,
  onStart,
}: {
  batchId: string;
  readiness: RetrainReadiness | null;
  job: JobOut | null;
  jobBatchId: string | null;
  lastRun: RetrainRunOut | null;
  starting: boolean;
  error: string | null;
  onStart: (
    batchId: string,
    params: RetrainParams,
    withoutReplay: boolean,
  ) => void;
}) {
  const [confirming, setConfirming] = useState<null | "full" | "replayless">(
    null,
  );
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

      <div
        className={`rounded-lg border border-slate-200 bg-white px-3 py-2 ${
          // A confirmation carries a choice with consequences and several
          // sentences explaining it; squeezed into a third of the row it
          // becomes a column of two-word lines nobody reads.
          confirming !== null ? "basis-full" : "min-w-[16rem] flex-1"
        }`}
      >
        <div className="text-[11px] font-semibold text-slate-700">
          2 · Re-train
        </div>
        <RetrainControl
          batchId={batchId}
          readiness={readiness}
          job={job}
          jobBatchId={jobBatchId}
          lastRun={lastRun}
          starting={starting}
          error={error}
          confirming={confirming}
          setConfirming={setConfirming}
          onStart={onStart}
        />
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
          Nothing a run produces grades anyone until someone approves it here.
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
 * The same two steps the button runs, as commands.
 *
 * Kept because the button is not the only way in: a run on a machine with a
 * GPU, or with different parameters, is still a terminal job, and the batch id
 * is what makes any past run reproducible.
 */
function retrainCommands(
  batchId: string,
  activeCheckpoint: string,
  replayDir: string | null,
): string {
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
    `    --replay-dir ${replayDir ?? REPLAY_DIR_PLACEHOLDER} \\`,
    `    --out-checkpoint models/weights/${batchId}.pth`,
  ].join("\n");
}

function BatchCard({
  batch,
  rows,
  activeCheckpoint,
  readiness,
  job,
  jobBatchId,
  lastRun,
  starting,
  error,
  onStart,
}: {
  batch: BatchOut;
  /** The rows of this batch the server actually returned (may be partial). */
  rows: CorrectionOut[];
  activeCheckpoint: string;
  readiness: RetrainReadiness | null;
  job: JobOut | null;
  jobBatchId: string | null;
  /** The newest run recorded for this batch, if any. */
  lastRun: RetrainRunOut | null;
  starting: boolean;
  error: string | null;
  onStart: (
    batchId: string,
    params: RetrainParams,
    withoutReplay: boolean,
  ) => void;
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

      <LoopSteps
        batchId={batch.batch_id}
        readiness={readiness}
        job={job}
        jobBatchId={jobBatchId}
        lastRun={lastRun}
        starting={starting}
        error={error}
        onStart={onStart}
      />

      <details className="mt-3">
        <summary className="cursor-pointer text-[11px] font-medium text-slate-500">
          Or run the same two steps in a terminal
        </summary>
        <Commands
          title="What the button runs, as commands"
          code={retrainCommands(
            batch.batch_id,
            activeCheckpoint,
            readiness?.replay_present ? readiness.replay_dir : null,
          )}
        />
      </details>
    </article>
  );
}

// --- The run log -----------------------------------------------------------

const RUN_METRICS: { key: string; label: string }[] = [
  { key: "macro_f1", label: "Macro F1" },
  { key: "severe_f1", label: "Severe F1" },
  { key: "mean_acc", label: "Mean accuracy" },
];

function RunBadge({ run }: { run: RetrainRunOut }) {
  const [text, cls] =
    run.status === "running"
      ? ["Running", "bg-indigo-100 text-indigo-700"]
      : run.status === "error"
        ? ["Failed", "bg-rose-100 text-rose-700"]
        : run.status === "interrupted"
          ? ["Interrupted", "bg-amber-100 text-amber-800"]
          : run.improved
            ? ["Candidate saved", "bg-emerald-100 text-emerald-700"]
            : ["No improvement", "bg-slate-100 text-slate-600"];
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {text}
    </span>
  );
}

/** Before/after on the frozen held-out set, as the run measured it. */
function RunMetrics({ run }: { run: RetrainRunOut }) {
  if (!run.before || !run.after) return null;
  // A metric the run could not measure comes back as null (a class with no
  // support in the held-out set); showing "—" for it would suggest a number
  // was expected, so the row is simply left out.
  const rows = RUN_METRICS.map((m) => ({
    ...m,
    before: run.before?.[m.key],
    after: run.after?.[m.key],
  })).filter(
    (m): m is { key: string; label: string; before: number; after: number } =>
      typeof m.before === "number" && typeof m.after === "number",
  );
  if (rows.length === 0) return null;

  return (
    <table className="mt-2 w-full max-w-md text-[11px]">
      <thead>
        <tr className="text-slate-500">
          <th className="py-0.5 text-left font-medium">
            On the frozen held-out set
          </th>
          <th className="py-0.5 text-right font-medium">Before</th>
          <th className="py-0.5 text-right font-medium">After</th>
          <th className="py-0.5 text-right font-medium">Change</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((m) => {
          const { before, after } = m;
          const delta = after - before;
          const cls =
            delta === 0
              ? "text-slate-400"
              : delta > 0
                ? "text-emerald-600"
                : "text-rose-600";
          return (
            <tr key={m.key} className="border-t border-slate-200">
              <td className="py-0.5 text-slate-700">{m.label}</td>
              <td className="py-0.5 text-right tabular-nums text-slate-500">
                {before.toFixed(3)}
              </td>
              <td className="py-0.5 text-right font-semibold tabular-nums text-slate-800">
                {after.toFixed(3)}
              </td>
              <td className={`py-0.5 text-right font-semibold tabular-nums ${cls}`}>
                {delta > 0 ? "+" : delta < 0 ? "−" : "±"}
                {Math.abs(delta).toFixed(3)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * True when nothing moved at all between before and after.
 *
 * Three identical rows and three ±0.000 changes read like a broken
 * measurement. They are not: `retrain_head` restores the best-scoring state it
 * saw, so a run where no epoch beat the starting point ends on exactly the
 * weights it began with. Worth one sentence, because the alternative reading
 * is that the numbers are fake.
 */
function unchangedMetrics(run: RetrainRunOut): boolean {
  const before = run.before ?? {};
  const after = run.after ?? {};
  const keys = Object.keys(after).filter((k) => typeof after[k] === "number");
  return (
    keys.length > 0 && keys.every((k) => before[k] === after[k])
  );
}


function paramSummary(run: RetrainRunOut): string {
  const p = run.params ?? {};
  const bits = [
    // Scope first: two runs launched from one batch with different scopes saw
    // different data, and nothing else in the row would tell them apart. A row
    // with no scope recorded is from before the choice existed — per-batch.
    p.scope === "all" ? "all corrections so far" : "this batch only",
    `${p.epochs ?? "?"} epoch${p.epochs === 1 ? "" : "s"} max`,
    `lr ${p.lr ?? "?"}`,
    `batch ${p.batch_size ?? "?"}`,
    p.replay_dir
      ? `${p.replay_size ?? 0} replay discs`
      : "no replay set (weaker)",
    `on ${p.device ?? "cpu"}`,
  ];
  return bits.join(" · ");
}

function RunCard({ run, job }: { run: RetrainRunOut; job: JobOut | null }) {
  const live = run.status === "running" && job?.id === run.job_id ? job : null;
  return (
    <article className="mb-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <RunBadge run={run} />
        <span className="text-[11px] text-slate-500">
          launched from{" "}
          <span className="font-mono text-slate-700">{run.batch_id}</span>
        </span>
        <span className="text-[11px] text-slate-500">
          started {formatDate(run.started_at)}
          {run.duration_seconds != null && (
            <> · took {formatDuration(run.duration_seconds)}</>
          )}
        </span>
      </div>

      <p className="mt-1 text-[11px] text-slate-500">
        {paramSummary(run)}
        {run.n_rows != null && (
          <>
            {" · "}
            {run.n_corrections ?? 0} correction
            {run.n_corrections === 1 ? "" : "s"} → {run.n_rows} disc
            {run.n_rows === 1 ? "" : "s"} rebuilt
          </>
        )}
        {run.params?.base_checkpoint != null && (
          <>
            {" · from "}
            <span className="font-mono">{String(run.params.base_checkpoint)}</span>
          </>
        )}
      </p>

      {live && <RunningPanel job={live} />}

      <RunMetrics run={run} />

      {run.status === "done" && run.improved && run.checkpoint_name && (
        <p className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-800">
          Candidate <span className="font-mono">{run.checkpoint_name}</span>{" "}
          {run.checkpoint_exists ? "written" : "was written but is gone"} ·{" "}
          {run.checkpoint_active ? (
            <>it was since approved and is now in service.</>
          ) : (
            <>
              it grades nobody until someone approves it on{" "}
              <Link to="/models" className="font-semibold underline">
                Model versions
              </Link>
              .
            </>
          )}
        </p>
      )}

      {run.status === "done" && run.improved === false && (
        <p className="mt-2 rounded-md bg-slate-50 px-2 py-1 text-[11px] leading-snug text-slate-600">
          Held-out macro-F1 did not improve, so no checkpoint was written. That
          is the run working as intended, not a failure: the gate in{" "}
          <code className="rounded bg-slate-100 px-1">retrain_head</code> only
          keeps a model that measures better.
          {unchangedMetrics(run) && (
            <>
              {" "}
              Every measure is identical because the run ended on the weights it
              started from — it keeps the best-scoring state it saw, and no
              epoch scored better than the start.
            </>
          )}
        </p>
      )}

      {run.error && (
        <p className="mt-2 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] leading-snug text-rose-700">
          {run.error}
        </p>
      )}

      {run.skipped != null && run.skipped.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[11px] font-medium text-slate-500">
            {run.skipped.length} disc
            {run.skipped.length === 1 ? "" : "s"} skipped when rebuilding
          </summary>
          <ul className="mt-1 space-y-0.5 text-[11px] text-slate-500">
            {run.skipped.map((reason) => (
              <li key={reason} className="font-mono">
                {reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

// --- The page --------------------------------------------------------------

export default function Admin() {
  const [queue, setQueue] = useState<CorrectionQueue | null>(null);
  const [sent, setSent] = useState<CorrectionOut[]>([]);
  const [batches, setBatches] = useState<BatchOut[] | null>(null);
  /** True when the batch list had to be rebuilt from rows, so it may be partial. */
  const [batchesDerived, setBatchesDerived] = useState(false);
  const [activeCheckpoint, setActiveCheckpoint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [readiness, setReadiness] = useState<RetrainReadiness | null>(null);
  const [runs, setRuns] = useState<RetrainRunOut[] | null>(null);
  const [job, setJob] = useState<JobOut | null>(null);
  const [jobBatchId, setJobBatchId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  /** Guards against adopting a run twice while the first poll is in flight. */
  const adopted = useRef<string | null>(null);

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

  /** Readiness + the run log. Cheap, and re-read on every poll tick. */
  const loadRetraining = useCallback(() => {
    // A backend without these endpoints simply has no trigger; the rest of the
    // page still works, so the failure is recorded as "no readiness" and the
    // button stays disabled with its reason.
    getRetrainReadiness()
      .then(setReadiness)
      .catch(() => setReadiness(null));
    return getRetrainRuns(20)
      .then((list) => {
        setRuns(list);
        return list;
      })
      .catch(() => {
        setRuns(null);
        return null;
      });
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    loadRetraining();
  }, [loadRetraining]);

  // Adopt a run that was already going when this page opened — started from
  // another tab, or before a reload. Leaving the page must not lose the run.
  useEffect(() => {
    const running = runs?.find((r) => r.status === "running" && r.job_id);
    if (!running?.job_id || adopted.current === running.job_id) return;
    adopted.current = running.job_id;
    setJobBatchId(running.batch_id);
    getJob(running.job_id)
      .then(setJob)
      .catch(() => setJob(null));
  }, [runs]);

  // Poll while a run is in flight, then refresh everything once it settles.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const timer = setInterval(() => {
      getJob(job.id)
        .then((next) => {
          setJob(next);
          if (next.status !== "running") loadRetraining();
        })
        .catch(() => {
          // The server restarted, or the job aged out of the in-memory
          // registry. The run log is the durable record; fall back to it.
          setJob(null);
          loadRetraining();
        });
      loadRetraining();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [job, loadRetraining]);

  async function handleStart(
    batchId: string,
    params: RetrainParams,
    withoutReplay: boolean,
  ) {
    setStarting(true);
    setStartError(null);
    try {
      const started = await startBatchRetrain(batchId, {
        scope: params.scope,
        epochs: params.epochs,
        replay_size: params.replay_size,
        without_replay: withoutReplay,
      });
      adopted.current = started.id;
      setJobBatchId(batchId);
      setJob(started);
      loadRetraining();
    } catch (err: unknown) {
      setStartError(err instanceof Error ? err.message : String(err));
      loadRetraining();
    } finally {
      setStarting(false);
    }
  }

  const checkpointForCommands = activeCheckpoint ?? "phase2_cbam.pth";
  const rowsByBatch = new Map<string, CorrectionOut[]>();
  for (const row of sent) {
    if (!row.batch_id) continue;
    const list = rowsByBatch.get(row.batch_id);
    if (list) list.push(row);
    else rowsByBatch.set(row.batch_id, [row]);
  }

  const latestRunByBatch = new Map<string, RetrainRunOut>();
  for (const run of runs ?? []) {
    if (!latestRunByBatch.has(run.batch_id)) latestRunByBatch.set(run.batch_id, run);
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
              What doctors corrected, what went out in which batch, and what
              re-training made of it
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
          Developer view. There is no access control on this page — anyone who
          can open the app can open it, and the API answers the same requests
          directly, including the one that starts a training run. That is a
          deliberate choice for a demo, not a security boundary.
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
              The button in any patient's viewer seals{" "}
              <strong>every correction waiting anywhere</strong> into one batch.
              Intended: a single study is too few discs to fine-tune on.
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
              <p className="mt-2 text-xs text-slate-500">
                The normal resting state. A saved grade change adds a row here;
                “Send corrections” seals the rows into a batch, listed below.
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
                holds, which studies they came from, and the button that
                re-trains on exactly those corrections.
              </p>
            </div>
          ) : (
            batches.map((batch) => (
              <BatchCard
                key={batch.batch_id}
                batch={batch}
                rows={rowsByBatch.get(batch.batch_id) ?? []}
                activeCheckpoint={checkpointForCommands}
                readiness={readiness}
                job={job}
                jobBatchId={jobBatchId}
                lastRun={latestRunByBatch.get(batch.batch_id) ?? null}
                starting={starting}
                error={jobBatchId === batch.batch_id ? startError : null}
                onStart={handleStart}
              />
            ))
          )}
        </section>

        {/* Run history ---------------------------------------------------- */}
        <section className="mt-6">
          <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-indigo-500 to-violet-500" />
            Re-training runs
          </h2>

          {runs === null ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm shadow-sm">
              <p className="font-medium text-slate-700">
                This backend does not keep a run log.
              </p>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                It predates <code>/retraining/runs</code>, so re-training can
                only be started from a terminal here, and nothing on this page
                can say whether it ever was.
              </p>
            </div>
          ) : runs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm shadow-sm">
              <p className="font-medium text-slate-700">
                No run has been started on this server.
              </p>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                Every attempt lands here — which batch it used, when it started
                and finished, the parameters, the before/after numbers on the
                frozen held-out set, and whether a candidate came out of it.
                Runs that found no improvement are kept too; they are the
                normal case, and a loop with no record of them cannot be
                audited.
              </p>
            </div>
          ) : (
            runs.map((run) => <RunCard key={run.id} run={run} job={job} />)
          )}
        </section>

        {/* Preconditions ---------------------------------------------------- */}
        <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-800">
            <span className="h-4 w-1 rounded bg-gradient-to-b from-slate-400 to-slate-500" />
            What a run needs
          </h2>

          {/* Two facts a run depends on, as status rows rather than prose. The
              long-form reasoning lives in DEPLOY_VAST.md and the thesis report;
              this page only has to say whether the machine is ready. */}
          <dl className="space-y-2 text-xs">
            <div className="flex items-baseline gap-2">
              <dt className="w-32 shrink-0 font-semibold text-slate-700">
                Held-out set
              </dt>
              <dd className="text-slate-600">
                {readiness?.holdout_present ? (
                  <span className="font-medium text-emerald-700">present</span>
                ) : (
                  <span className="font-medium text-rose-700">
                    missing or changed
                  </span>
                )}
                {" — "}
                {readiness?.holdout_rows ?? 200} rows, frozen before any
                correction. Every before/after number is measured on it.
                {readiness?.holdout_message && (
                  <span className="block text-[11px] text-slate-400">
                    {readiness.holdout_message}
                  </span>
                )}
              </dd>
            </div>

            <div className="flex items-baseline gap-2">
              <dt className="w-32 shrink-0 font-semibold text-slate-700">
                Replay set
              </dt>
              <dd className="text-slate-600">
                {readiness?.replay_present ? (
                  <span className="font-medium text-emerald-700">
                    present ({readiness.replay_rows ?? "?"} discs)
                  </span>
                ) : (
                  <span className="font-medium text-amber-700">
                    {readiness?.replay_configured
                      ? "configured but not on this machine"
                      : "not configured"}
                  </span>
                )}
                {" — "}~200 original discs mixed in so the heads do not forget.
                Set{" "}
                <code className="rounded bg-slate-100 px-1">
                  {readiness?.replay_setting ?? "RETRAIN_REPLAY_DIR"}
                </code>{" "}
                in <code className="rounded bg-slate-100 px-1">backend/.env</code>
                .
              </dd>
            </div>

            <div className="flex items-baseline gap-2">
              <dt className="w-32 shrink-0 font-semibold text-slate-700">
                Scope
              </dt>
              <dd className="text-slate-600">
                Canal and left/right foraminal only. The other eight come from
                upstream SpineNet and are marked{" "}
                <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
                  not re-trained
                </span>
                .
              </dd>
            </div>

            <div className="flex items-baseline gap-2">
              <dt className="w-32 shrink-0 font-semibold text-slate-700">
                Cost
              </dt>
              <dd className="text-slate-600">
                Tens of minutes on{" "}
                <code className="rounded bg-slate-100 px-1">
                  {String(readiness?.defaults?.device ?? "cpu")}
                </code>
                . One run at a time. Closing the page does not stop it.
              </dd>
            </div>
          </dl>

          <p className="mt-4 rounded-md bg-slate-50 px-2.5 py-2 text-xs text-slate-500">
            <span className="font-semibold text-slate-600">
              Nothing here is automatic.
            </span>{" "}
            Sealing a batch does not start a run; a finished run does not go
            into service. It leaves a candidate for a person to approve on{" "}
            <Link to="/models" className="text-indigo-600 hover:underline">
              Model versions
            </Link>
            . That gap is what stops one patient's correction from changing the
            next patient's result.
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
