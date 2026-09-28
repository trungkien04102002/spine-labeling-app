import { useState, type FormEvent } from "react";

import { joinRoom } from "../lib/api";
import { LangToggle, useT } from "../lib/i18n";
import { useRoom } from "../lib/room";

/**
 * The door: type a name, get a room. Kahoot-style on purpose.
 *
 * No account, because the trial is short and asking clinicians to register is
 * where they give up. The same name on any device returns to the same room,
 * which is said on the screen so nobody is surprised to find their studies
 * waiting -- or someone else's, if two people pick the same name.
 */
export default function Join() {
  const { t } = useT();
  const { enter } = useRoom();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const room = await joinRoom(name.trim());
      enter({ id: room.id, name: room.name });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-gradient-to-br from-teal-600 to-cyan-500">
      <div className="flex justify-end p-4">
        <LangToggle />
      </div>
      <div className="flex flex-1 items-center justify-center px-4 pb-16">
        <form
          onSubmit={submit}
          className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl"
        >
          <h1 className="text-2xl font-bold text-slate-800">Spine Labeling</h1>
          <p className="mt-1 text-sm text-slate-500">
            {t("Lumbar MRI · AI-assisted grading")}
          </p>

          <label className="mt-8 block text-sm font-semibold text-slate-700" htmlFor="room-name">
            {t("Your name")}
          </label>
          <input
            id="room-name"
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={128}
            placeholder={t("e.g. Dr. Minh")}
            className="mt-2 w-full rounded-lg border-2 border-slate-200 px-4 py-3 text-lg focus:border-teal-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={!name.trim() || busy}
            className="mt-4 w-full rounded-lg bg-teal-600 py-3 text-base font-bold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {busy ? t("Entering…") : t("Enter my room")}
          </button>

          {error && (
            <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
          )}

          <ul className="mt-6 space-y-1.5 text-xs leading-relaxed text-slate-500">
            <li>• {t("Each person gets a private room: your studies, your corrections and your answers are seen by no other participant.")}</li>
            <li>• {t("Type the same name again, on any computer, to come back to your room.")}</li>
            <li>• {t("Pick a name others will not use — two people with the same name share one room.")}</li>
          </ul>
        </form>
      </div>
    </div>
  );
}
