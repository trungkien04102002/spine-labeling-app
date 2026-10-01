import { useEffect, useState, type FormEvent } from "react";

import PinSetup, { PinInput, PinPairFields, usePinPair } from "../components/PinSetup";
import { getPublicRooms, joinRoom, type PublicRoom, type RoomOut } from "../lib/api";
import { LangToggle, useT } from "../lib/i18n";
import { useRoom, writeRoom } from "../lib/room";

/** Same identity rule as the backend's reader_key: case and spacing ignored. */
function nameKey(name: string): string {
  return name.replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

/**
 * The door: pick your name, type your PIN.
 *
 * Typing a name on every visit split clinicians in two ("Minh" today,
 * "BS Minh" tomorrow) and left them unable to find their own studies. A list
 * to pick from removes the typing; the PIN stops a tap on the wrong name from
 * opening a colleague's room. New clinicians make a room once, with the PIN
 * typed twice so a slip of the finger does not lock them out.
 */
export default function Join({ linkError = null }: { linkError?: string | null }) {
  const { t } = useT();
  const { enter } = useRoom();
  const [rooms, setRooms] = useState<PublicRoom[] | null>(null);
  const [mode, setMode] = useState<"pick" | "new">("pick");
  const [picked, setPicked] = useState<PublicRoom | null>(null);
  const [pin, setPin] = useState("");
  const [newName, setNewName] = useState("");
  const pair = usePinPair();
  // A room entered without a PIN (made before PINs, or reset in /admin) has
  // to get one before the clinician goes in.
  const [needsPin, setNeedsPin] = useState<RoomOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPublicRooms()
      .then((list) => {
        setRooms(list);
        if (list.length === 0) setMode("new");
      })
      .catch(() => setRooms([]));
  }, []);

  const clash = rooms?.find((r) => nameKey(r.name) === nameKey(newName)) ?? null;

  async function go(name: string, pinValue?: string) {
    setBusy(true);
    setError(null);
    try {
      const room = await joinRoom(name, pinValue);
      if (room.has_pin) enter({ id: room.id, name: room.name });
      else {
        // PinSetup's request has to carry this room, so store it now -- but
        // only in storage: entering the room in context would leave the door.
        writeRoom({ id: room.id, name: room.name });
        setNeedsPin(room);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(
        /wrong pin/i.test(msg)
          ? t("Wrong PIN. Forgot it? Ask the organiser to send you your personal link again.")
          : t(msg),
      );
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  function submitPick(e: FormEvent) {
    e.preventDefault();
    if (!picked) return;
    if (picked.has_pin && pin.length !== 4) return;
    void go(picked.name, picked.has_pin ? pin : undefined);
  }

  function submitNew(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim() || clash || !pair.ok) return;
    void go(newName.trim(), pair.pin);
  }

  const card = "w-full max-w-md rounded-2xl bg-white p-8 shadow-xl";
  const primary =
    "mt-4 w-full rounded-lg bg-teal-600 py-3 text-base font-bold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:bg-slate-300";
  const linkBtn = "text-sm font-semibold text-teal-700 hover:underline";

  let body;
  if (needsPin) {
    body = (
      <div className={card}>
        <h1 className="text-xl font-bold text-slate-800">
          {t("Hello, {name}", { name: needsPin.name })}
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          {t("Your room has no PIN yet. Choose one so that next time you can come back by picking your name and typing it.")}
        </p>
        <PinSetup onDone={(room) => enter({ id: room.id, name: room.name })} />
      </div>
    );
  } else if (mode === "pick" && picked) {
    body = (
      <form onSubmit={submitPick} className={card}>
        <p className="text-sm text-slate-500">{t("Entering the room of")}</p>
        <h1 className="mt-1 text-2xl font-bold text-slate-800">{picked.name}</h1>
        {picked.has_pin ? (
          <>
            <label className="mt-6 block text-sm font-semibold text-slate-700" htmlFor="door-pin">
              {t("Your 4-digit PIN")}
            </label>
            <PinInput id="door-pin" value={pin} onChange={setPin} autoFocus />
          </>
        ) : (
          <p className="mt-4 text-sm text-slate-600">
            {t("This room has no PIN yet — you will choose one after entering.")}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || (picked.has_pin && pin.length !== 4)}
          className={primary}
        >
          {busy ? t("Entering…") : t("Enter my room")}
        </button>
        {error && (
          <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
        )}
        <button
          type="button"
          className={`${linkBtn} mt-5`}
          onClick={() => {
            setPicked(null);
            setPin("");
            setError(null);
          }}
        >
          ← {t("Not you? Pick another name")}
        </button>
      </form>
    );
  } else if (mode === "pick") {
    body = (
      <div className={card}>
        <h1 className="text-2xl font-bold text-slate-800">Spine Labeling</h1>
        <p className="mt-1 text-sm text-slate-500">{t("Lumbar MRI · AI-assisted grading")}</p>
        <h2 className="mt-8 text-sm font-semibold text-slate-700">{t("Pick your name")}</h2>
        {rooms === null ? (
          <p className="mt-3 text-sm text-slate-400">{t("Loading…")}</p>
        ) : (
          <div className="mt-3 flex max-h-72 flex-wrap gap-2 overflow-y-auto">
            {rooms.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => {
                  setPicked(r);
                  setError(null);
                }}
                className="rounded-lg border-2 border-slate-200 px-4 py-2 text-base font-medium text-slate-700 transition hover:border-teal-500 hover:bg-teal-50"
              >
                {r.name}
              </button>
            ))}
          </div>
        )}
        <div className="mt-6 border-t border-slate-200 pt-4">
          <p className="text-sm text-slate-600">{t("First time here, and your name is not in the list?")}</p>
          <button type="button" className={`${linkBtn} mt-1`} onClick={() => setMode("new")}>
            {t("Create my room")} →
          </button>
        </div>
        {linkError && (
          <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {t("This link does not match any room. Ask for your link again, or pick your name.")}
          </p>
        )}
      </div>
    );
  } else {
    body = (
      <form onSubmit={submitNew} className={card}>
        <h1 className="text-xl font-bold text-slate-800">{t("Create my room")}</h1>
        <p className="mt-1 text-sm text-slate-500">
          {t("Only once. Next time, pick your name from the list and type your PIN.")}
        </p>
        <label className="mt-6 block text-sm font-semibold text-slate-700" htmlFor="room-name">
          {t("Your name")}
        </label>
        <input
          id="room-name"
          autoFocus
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          maxLength={128}
          placeholder={t("e.g. Dr. Minh")}
          className="mt-2 w-full rounded-lg border-2 border-slate-200 px-4 py-3 text-lg focus:border-teal-500 focus:outline-none"
        />
        {clash && (
          <p className="mt-2 text-sm text-amber-700">
            {t("“{name}” already has a room.", { name: clash.name })}{" "}
            <button
              type="button"
              className="font-semibold underline"
              onClick={() => {
                setMode("pick");
                setPicked(clash);
                setNewName("");
              }}
            >
              {t("Enter that room")}
            </button>
          </p>
        )}
        <PinPairFields pair={pair} idPrefix="new" />
        <button
          type="submit"
          disabled={busy || !newName.trim() || !!clash || !pair.ok}
          className={primary}
        >
          {busy ? t("Entering…") : t("Create my room")}
        </button>
        {error && (
          <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
        )}
        {(rooms?.length ?? 0) > 0 && (
          <button
            type="button"
            className={`${linkBtn} mt-5`}
            onClick={() => {
              setMode("pick");
              setError(null);
            }}
          >
            ← {t("Back to the list of names")}
          </button>
        )}
      </form>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-gradient-to-br from-teal-600 to-cyan-500">
      <div className="flex justify-end p-4">
        <LangToggle />
      </div>
      <div className="flex flex-1 items-center justify-center px-4 pb-16">{body}</div>
    </div>
  );
}
