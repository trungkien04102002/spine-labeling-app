import { useEffect, useState } from "react";
import { apiFetch } from "./api";

/** Deployment facts the pages need before rendering (backend /app_config). */
export type AppConfig = { view_only: boolean };

let cached: Promise<AppConfig> | null = null;

function load(): Promise<AppConfig> {
  cached ??= apiFetch<AppConfig>("/app_config").catch(() => {
    cached = null; // try again on the next page rather than stick to a guess
    return { view_only: false };
  });
  return cached;
}

/**
 * Whether this box is view-only: clinicians look at studies already graded,
 * with no editing, uploading or grading. `null` until known, so a page can
 * avoid flashing controls it is about to hide.
 */
export function useViewOnly(): boolean | null {
  const [v, setV] = useState<boolean | null>(null);
  useEffect(() => {
    load().then((c) => setV(c.view_only));
  }, []);
  return v;
}
