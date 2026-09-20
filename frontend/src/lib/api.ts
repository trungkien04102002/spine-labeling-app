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

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new Error(
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
