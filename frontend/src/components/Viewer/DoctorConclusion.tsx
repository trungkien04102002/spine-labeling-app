import { useEffect, useState } from "react";
import { saveConclusion } from "../../lib/api";
import { useT } from "../../lib/i18n";

/**
 * The clinician's own conclusion for the scan, in their words.
 *
 * Asked for by a clinician trying the app (2026-10-06): the grade buttons
 * cannot say everything a report says ("L4-L5 herniation to the left,
 * touching the L5 root"), and a reader wants to write the final word on the
 * study themselves. One free-text box per study, saved with its own button.
 */
export default function DoctorConclusion({
  studyId,
  initialText,
  initialSavedAt,
}: {
  studyId: string;
  initialText: string | null | undefined;
  initialSavedAt: string | null | undefined;
}) {
  const { t } = useT();
  const [text, setText] = useState(initialText ?? "");
  const [savedText, setSavedText] = useState(initialText ?? "");
  const [savedAt, setSavedAt] = useState<string | null>(initialSavedAt ?? null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A different study, or the same one reloaded: start from what is stored.
  useEffect(() => {
    setText(initialText ?? "");
    setSavedText(initialText ?? "");
    setSavedAt(initialSavedAt ?? null);
  }, [studyId, initialText, initialSavedAt]);

  const changed = text.trim() !== savedText.trim();

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const res = await saveConclusion(studyId, text);
      setSavedText(res.text ?? "");
      setText(res.text ?? "");
      setSavedAt(res.saved_at);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-1 flex items-center gap-2 text-base font-bold text-slate-800">
        <span className="h-4 w-1 rounded bg-gradient-to-b from-teal-500 to-cyan-500" />
        {t("Doctor's conclusion")}
      </h2>
      <p className="text-xs text-slate-600">
        {t("Write your own conclusion for this scan, in your words, if you wish: anything the grade buttons cannot say. Do not write the patient's name or other identifying details.")}
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        maxLength={4000}
        placeholder={t("e.g. L4-L5 disc herniation to the left, touching the L5 root; mild canal stenosis.")}
        className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800"
      />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={!changed || saving}
          className="rounded-lg bg-teal-600 px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {saving ? t("Saving…") : t("Save conclusion")}
        </button>
        {changed ? (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
            {t("unsaved")}
          </span>
        ) : (
          savedAt && (
            <span className="text-xs text-emerald-700">
              {t("Saved {when}", {
                when: new Date(savedAt.endsWith("Z") ? savedAt : savedAt + "Z").toLocaleString("vi-VN"),
              })}
            </span>
          )
        )}
        {error && <span className="text-xs text-rose-600">{error}</span>}
      </div>
    </div>
  );
}
