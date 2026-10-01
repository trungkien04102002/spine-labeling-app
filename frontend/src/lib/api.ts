import { readAdminKey, readRoom, writeRoom } from "./room";

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ??
  "http://localhost:8000";

export interface HealthResponse {
  status: string;
}

export interface StudyOut {
  id: string;
  modality: string;
  has_volume: boolean;
  created_at: string;
}

export interface PatientOut {
  id: number;
  name: string;
  created_at: string;
  studies: StudyOut[];
}

export interface UploadResponse {
  study_id: string;
  volume_path: string;
  display_path: string;
  series_count: number;
}

/** One acquisition (sagittal T1 / sagittal T2 / axial T2 ...) inside a study. */
export interface SeriesOut {
  id: number;
  series_uid: string;
  description: string | null;
  orientation: string;
  num_slices: number | null;
  is_active: boolean;
  /** The models read one acquisition, not all of them -- the UI says which. */
  analyzed_by_ai: boolean;
}

export interface StudyDetail {
  id: string;
  patient_id: number;
  patient_name: string;
  modality: string;
  created_at: string;
  has_volume: boolean;
  has_mask: boolean;
  dimensions: number[] | null;
  spacing_mm: number[] | null;
  num_slices: number | null;
  dicom_tags: Record<string, string>;
}

/** Room and operator headers for a request, read fresh from storage. */
function contextHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const room = readRoom();
  if (room) headers["X-Reader-Id"] = String(room.id);
  const adminKey = readAdminKey();
  if (adminKey) headers["X-Admin-Key"] = adminKey;
  return headers;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  for (const [k, v] of Object.entries(contextHeaders())) {
    if (!headers.has(k)) headers.set(k, v);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    // FastAPI puts the reason in `detail`, and some of this app's refusals are
    // the whole message — "no replay set is configured, set RETRAIN_REPLAY_DIR
    // to …" is useless as "400 Bad Request". Fall back to the status line when
    // the body is not the shape we expect.
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON — the status line is all there is */
    }
    // The server no longer knows this browser's room (its database was
    // reset, or the box replaced). Staying would show an empty room that
    // cannot be written to; going back to the door lets them re-enter.
    if (response.status === 401 && readRoom() && /room no longer exists/i.test(detail)) {
      writeRoom(null);
      window.location.reload();
    }
    throw new Error(
      detail ||
        `API request failed: ${response.status} ${response.statusText}`,
    );
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

export function getPatients(): Promise<PatientOut[]> {
  return apiFetch<PatientOut[]>("/patients");
}

export function getStudyDetail(studyId: string): Promise<StudyDetail> {
  return apiFetch<StudyDetail>(`/studies/${studyId}`);
}

export function createStudy(
  id: string,
  patientName: string,
  modality: string,
): Promise<unknown> {
  return apiFetch("/studies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, patient_name: patientName, modality }),
  });
}

export function updateStudy(
  studyId: string,
  patch: { patient_name?: string; modality?: string },
): Promise<unknown> {
  return apiFetch(`/studies/${studyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function deleteStudy(studyId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/studies/${studyId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

export interface GradingItem {
  level: string;
  condition: string;
  severity: string;
  score: number;
  bbox: number[] | null;
  heatmap_uri: string | null;
}

export interface InferResult {
  study_id: string;
  segmentation: { mask_uri: string; labels: Record<string, string> };
  grading: GradingItem[];
  model_version: string;
}

/** Latest annotation results; rejects (404) if inference has not run. */
export function getAnnotation(studyId: string): Promise<InferResult> {
  return apiFetch<InferResult>(`/studies/${studyId}/annotation`);
}

export function runInference(studyId: string): Promise<InferResult> {
  return apiFetch<InferResult>(`/studies/${studyId}/infer`, { method: "POST" });
}

/** Save a corrected annotation as a new version. */
export function saveAnnotation(
  studyId: string,
  result: InferResult,
): Promise<InferResult> {
  return apiFetch<InferResult>(`/studies/${studyId}/annotations`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(result),
  });
}

/** Persist a doctor-edited labelmap (raw uint8 voxels, slice order z,y,x). */
export function saveMask(studyId: string, voxels: Uint8Array): Promise<unknown> {
  return apiFetch(`/studies/${studyId}/mask`, {
    method: "PUT",
    headers: { "Content-Type": "application/octet-stream" },
    body: voxels as unknown as BodyInit,
  });
}

/** URL of the export zip (original + mask + grades + labeled PNG). */
export function exportUrl(studyId: string): string {
  return `${API_BASE_URL}/studies/${studyId}/export`;
}

/**
 * The full 11-label radiological grading table (Oxford-SpineNet-demo style):
 * `canal_stenosis` / `left_foraminal` / `right_foraminal` come from the app's
 * fine-tuned CBAM model, the other 8 conditions (pfirrmann, disc_narrowing,
 * spondylolisthesis, upper/lower_endplate_defect, upper/lower_marrow,
 * disc_herniation) come from the vendored upstream SpineNet pipeline.
 */
export interface FullGradingResult {
  study_id: string;
  grading: GradingItem[];
  slice_image_uri: string;
  model_version: string;
  segmentation?: { mask_uri: string; labels: Record<string, string> } | null;
}

/** Run the full grading pipeline (SpineNet + CBAM) and cache the result. */
export function runFullGrading(studyId: string): Promise<FullGradingResult> {
  return apiFetch<FullGradingResult>(`/studies/${studyId}/grade_full`, {
    method: "POST",
  });
}

/** Most recently computed full grading (rejects with 404 if never run). */
export function getFullGrading(studyId: string): Promise<FullGradingResult> {
  return apiFetch<FullGradingResult>(`/studies/${studyId}/grade_full`);
}

export function fullGradingCsvUrl(studyId: string): string {
  return `${API_BASE_URL}/studies/${studyId}/grade_full.csv`;
}

export function fullGradingJsonUrl(studyId: string): string {
  return `${API_BASE_URL}/studies/${studyId}/grade_full.json`;
}

export function fullGradingSliceUrl(studyId: string): string {
  return `${API_BASE_URL}/studies/${studyId}/grade_full/slice.png`;
}

export function getSeries(studyId: string): Promise<SeriesOut[]> {
  return apiFetch<SeriesOut[]>(`/studies/${studyId}/series`);
}

export function setActiveSeries(
  studyId: string,
  seriesId: number,
): Promise<SeriesOut[]> {
  return apiFetch<SeriesOut[]>(`/studies/${studyId}/active_series`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ series_id: seriesId }),
  });
}

export function uploadStudy(studyId: string, file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<UploadResponse>(`/studies/${studyId}/upload`, {
    method: "POST",
    body: form,
  });
}

// --- Doctor corrections on their way to the model -------------------------

export interface CorrectionOut {
  id: number;
  study_id: string;
  field: string;
  old: string | null;
  new: string | null;
  at: string;
  submitted_at: string | null;
  batch_id: string | null;
}

export interface CorrectionQueue {
  pending: number;
  submitted: number;
  batches: number;
  recent: CorrectionOut[];
}

export interface SubmitResult {
  batch_id: string;
  submitted: number;
  message: string;
}

/** One sealed hand-off: the corrections `submitCorrections` stamped in one go. */
export interface BatchOut {
  batch_id: string;
  sealed_at: string | null;
  corrections: number;
  studies: string[];
}

/**
 * Corrections waiting to be handed over, plus what has already gone.
 *
 * `status` narrows the `recent` rows only — the three counts are always over
 * the whole log. A backend that predates the parameter ignores it and returns
 * a mixed list, so callers still have to filter what they get.
 */
export function getCorrections(
  limit = 20,
  status: "all" | "pending" | "submitted" = "all",
): Promise<CorrectionQueue> {
  return apiFetch<CorrectionQueue>(
    `/corrections?limit=${limit}&status=${status}`,
  );
}

/** Every sealed batch, newest first. Rejects with 404 on an older backend. */
export function getCorrectionBatches(): Promise<BatchOut[]> {
  return apiFetch<BatchOut[]>("/corrections/batches");
}

/**
 * Hand every pending correction to the model as one batch.
 *
 * This queues only — re-training happens offline and a new checkpoint has to
 * be activated deliberately, so pressing this can never change what the next
 * patient is graded by.
 */
export function submitCorrections(): Promise<SubmitResult> {
  return apiFetch<SubmitResult>("/corrections/submit", { method: "POST" });
}

export interface CheckpointOut {
  name: string;
  size_bytes: number;
  modified_at: string;
  is_active: boolean;
  is_baseline: boolean;
  metrics: Record<string, unknown> | null;
}

export function getModelVersions(): Promise<CheckpointOut[]> {
  return apiFetch<CheckpointOut[]>("/model/versions");
}

export function activateModel(checkpoint: string): Promise<CheckpointOut> {
  return apiFetch<CheckpointOut>("/model/activate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ checkpoint }),
  });
}

export function revertModel(): Promise<CheckpointOut> {
  return apiFetch<CheckpointOut>("/model/revert", { method: "POST" });
}

/**
 * One recorded decision to change the checkpoint that grades patients.
 *
 * The app's claim is that the model only ever changes because a person
 * decided it should; this is the record of those decisions, so the claim is
 * something the system can show rather than something the UI asserts. A
 * revert is one of them too — going back changes what the next patient is
 * graded by just as much as approving a candidate does.
 */
export interface ActivationOut {
  id: number;
  /** What this decision put into service. */
  checkpoint: string;
  /** What was in service immediately before it. */
  previous_checkpoint: string | null;
  action: "activate" | "revert";
  /** null == unattributed. There is no sign-in in this build, so the record
   *  says so instead of naming somebody the backend would have invented. */
  actor: string | null;
  at: string;
}

export function getModelActivations(limit = 20): Promise<ActivationOut[]> {
  return apiFetch<ActivationOut[]>(`/model/activations?limit=${limit}`);
}

// --- Long-running grading as a polled job ---------------------------------

export interface JobOut {
  id: string;
  status: "running" | "done" | "error";
  stage: string;
  percent: number;
  elapsed_seconds: number;
  error: string | null;
}

/**
 * Start full grading in the background.
 *
 * The synchronous `runFullGrading` holds a request open for the 8-15 minutes
 * the pipeline takes, which any reverse proxy in front of the app will cut
 * off. This returns as soon as the job is queued; poll `getJob` for progress.
 */
export function startFullGrading(studyId: string): Promise<JobOut> {
  return apiFetch<JobOut>(`/studies/${studyId}/grade_full/start`, {
    method: "POST",
  });
}

export function getJob(jobId: string): Promise<JobOut> {
  return apiFetch<JobOut>(`/jobs/${jobId}`);
}

// --- Re-training one batch, as a polled job -------------------------------

/**
 * What a re-training run needs, and which of those things the server has.
 *
 * The replay set is the interesting one: ~8.2 GB of original discs that live
 * in the research repo, not in this app, so on some machines it simply is not
 * there. That is a state the page shows rather than a silent fallback — a run
 * without it is a different, weaker experiment.
 */
export interface RetrainReadiness {
  replay_setting: string;
  replay_dir: string | null;
  replay_configured: boolean;
  replay_present: boolean;
  replay_rows: number | null;
  holdout_dir: string;
  holdout_present: boolean;
  holdout_rows: number | null;
  holdout_message: string;
  base_checkpoint: string;
  base_checkpoint_present: boolean;
  /** Distinct (study, field) corrections across every sealed batch: what a
   *  cumulative run trains on. A grade corrected twice counts once. */
  cumulative_corrections: number;
  sealed_batches: number;
  can_run: boolean;
  can_run_without_replay: boolean;
  blockers: string[];
  replay_blocker: string | null;
  defaults: Record<string, number | string>;
  running_batch_id: string | null;
}

/** One attempted run: what it used, how it ended, and what it measured. */
export interface RetrainRunOut {
  id: number;
  batch_id: string;
  job_id: string | null;
  status: "running" | "done" | "error" | "interrupted";
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  params: Record<string, unknown>;
  /** null while running; false = ran fine, held-out macro-F1 did not improve. */
  improved: boolean | null;
  checkpoint_name: string | null;
  checkpoint_exists: boolean;
  /** Whether that candidate was since approved on /models. Never by the run. */
  checkpoint_active: boolean;
  /** A measurement the run could not make (a class absent from the held-out
   *  set) comes back as null rather than NaN, which is not valid JSON. */
  before: Record<string, number | null> | null;
  after: Record<string, number | null> | null;
  n_corrections: number | null;
  n_rows: number | null;
  skipped: string[] | null;
  error: string | null;
}

export interface RetrainOptions {
  /** "all" (default) trains on every correction sent so far; "batch" on the
   *  launching batch alone, which is what makes a past run reproducible. */
  scope?: "all" | "batch";
  epochs?: number;
  lr?: number;
  batch_size?: number;
  replay_size?: number;
  /** Run without the replay set: deliberately weaker, never the default. */
  without_replay?: boolean;
}

export function getRetrainReadiness(): Promise<RetrainReadiness> {
  return apiFetch<RetrainReadiness>("/retraining/readiness");
}

export function getRetrainRuns(limit = 20): Promise<RetrainRunOut[]> {
  return apiFetch<RetrainRunOut[]>(`/retraining/runs?limit=${limit}`);
}

/**
 * Start one re-training run on a sealed batch. Poll `getJob` for progress.
 *
 * It produces a candidate checkpoint at most — it never activates anything,
 * so what the next patient is graded by is unchanged until a person approves
 * the candidate on `/models`.
 */
export function startBatchRetrain(
  batchId: string,
  options: RetrainOptions = {},
): Promise<JobOut> {
  return apiFetch<JobOut>(`/corrections/batches/${batchId}/retrain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
}


// ---------------------------------------------------------------- survey ---

export type SurveyQuestion = {
  id: number;
  text: string;
  kind: "usability" | "core" | "detail";
  group: string;
  required: boolean;
  matrix: boolean;
};

export type SurveyForm = {
  questions: SurveyQuestion[];
  groups: string[];
  scale: { min: number; max: number; labels: string[] };
};

export type SurveyQuestionStat = SurveyQuestion & {
  n: number;
  mean: number | null;
  distribution: Record<string, number>;
};

type Block = { mean: number | null; answers: number };

export type SurveySummary = {
  responses: number;
  clinical: Block;
  usability: Block;
  groups: (Block & { name: string })[];
  questions: SurveyQuestionStat[];
  comments: { at: string; role: string | null; text: string }[];
};

/** The questionnaire itself. Served, not duplicated here, so it cannot drift. */
export function getSurveyForm(): Promise<SurveyForm> {
  return apiFetch<SurveyForm>("/survey/questions");
}

export function submitSurvey(payload: {
  answers: Record<number, number>;
  respondent?: string;
  role?: string;
  comment?: string;
}): Promise<{ id: number; clinical_mean: number | null }> {
  return apiFetch("/survey/responses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getSurveySummary(): Promise<SurveySummary> {
  return apiFetch<SurveySummary>("/survey/summary");
}

// ------------------------------------------------------------------- rooms ---

export type RoomOut = {
  id: number;
  name: string;
  code: string;
  created: boolean;
  has_pin: boolean;
  studies: number;
};

/** Enter (or create) a room by name. A room with a PIN needs it. */
export function joinRoom(name: string, pin?: string): Promise<RoomOut> {
  return apiFetch<RoomOut>("/readers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pin ? { name, pin } : { name }),
  });
}

export type PublicRoom = { id: number; name: string; has_pin: boolean };

/** The names a clinician picks from at the door. */
export function getPublicRooms(): Promise<PublicRoom[]> {
  return apiFetch<PublicRoom[]>("/readers/public");
}

export function getMyRoom(): Promise<RoomOut> {
  return apiFetch<RoomOut>("/readers/me");
}

/** Give the current room its PIN (only while it has none). */
export function setMyPin(pin: string): Promise<RoomOut> {
  return apiFetch<RoomOut>("/readers/me/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin }),
  });
}

/** /admin: forget a room's PIN so its clinician can choose a new one. */
export function resetRoomPin(id: number): Promise<{ id: number; has_pin: boolean }> {
  return apiFetch(`/readers/${id}/pin`, { method: "DELETE" });
}

/** Follow a personal link (/?phong=<code>) into its room. */
export function enterByCode(code: string): Promise<RoomOut> {
  return apiFetch<RoomOut>(`/readers/code/${encodeURIComponent(code)}`);
}

export type SampleOut = { id: string; added: boolean };

export function getSamples(): Promise<SampleOut[]> {
  return apiFetch<SampleOut[]>("/samples");
}

export function addSample(roomId: number, sampleId: string): Promise<{ id: string; created: boolean }> {
  return apiFetch(`/readers/${roomId}/samples/${encodeURIComponent(sampleId)}`, { method: "POST" });
}

// ------------------------------------------------------------ operator ---

export type RoomSummary = {
  id: number;
  name: string;
  code: string;
  has_pin: boolean;
  created_at: string;
  studies: number;
  corrections: number;
  surveys: number;
};

export function getRooms(): Promise<RoomSummary[]> {
  return apiFetch<RoomSummary[]>("/readers");
}

export function getAdminStatus(): Promise<{ locked: boolean }> {
  return apiFetch("/admin/status");
}

export function adminLogin(password: string): Promise<{ ok: boolean }> {
  return apiFetch("/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
}

export type SurveyResponseOut = {
  id: number;
  reader_id: number | null;
  submitted_at: string;
  respondent: string | null;
  role: string | null;
  clinical_mean: number | null;
  answers: Record<string, number>;
  comment: string | null;
};

export function getSurveyResponses(): Promise<SurveyResponseOut[]> {
  return apiFetch<SurveyResponseOut[]>("/survey/responses");
}

export async function deleteSurveyResponse(id: number): Promise<void> {
  const key = readAdminKey();
  const res = await fetch(`${API_BASE_URL}/survey/responses/${id}`, {
    method: "DELETE",
    headers: key ? { "X-Admin-Key": key } : {},
  });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

/**
 * Download a locked file. A plain link cannot carry the passphrase header, so
 * fetch it and hand the browser the bytes.
 */
export async function downloadLocked(path: string, fallbackName: string): Promise<void> {
  const key = readAdminKey();
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: key ? { "X-Admin-Key": key } : {},
  });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** The link that puts a clinician straight into their room. */
export function roomLink(code: string): string {
  return `${window.location.origin}/?phong=${code}`;
}

/**
 * Copy text, including on plain HTTP. navigator.clipboard only exists in a
 * secure context, and a rented box is usually served as http://IP:PORT -- there
 * the modern call is simply absent and a copy button would silently do
 * nothing. The legacy execCommand path still works on HTTP.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(area);
  return ok;
}
