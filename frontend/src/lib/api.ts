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

export function uploadStudy(studyId: string, file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<UploadResponse>(`/studies/${studyId}/upload`, {
    method: "POST",
    body: form,
  });
}
