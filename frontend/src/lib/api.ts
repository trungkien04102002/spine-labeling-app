const API_BASE_URL: string =
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

export function uploadStudy(studyId: string, file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<UploadResponse>(`/studies/${studyId}/upload`, {
    method: "POST",
    body: form,
  });
}
