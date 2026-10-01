import { useState, type FormEvent } from "react";

import { setMyPin, type RoomOut } from "../lib/api";
import { useT } from "../lib/i18n";

const FOUR_DIGITS = /^\d{4}$/;

/** A 4-digit PIN box: numeric keypad on phones, digits only, masked. */
export function PinInput({
  id,
  value,
  onChange,
  autoFocus = false,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  autoFocus?: boolean;
}) {
  return (
    <input
      id={id}
      type="password"
      inputMode="numeric"
      autoComplete="off"
      autoFocus={autoFocus}
      maxLength={4}
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 4))}
      className="mt-2 w-full rounded-lg border-2 border-slate-200 px-4 py-3 text-center text-2xl tracking-[0.5em] focus:border-teal-500 focus:outline-none"
    />
  );
}

/**
 * Two PIN boxes that must match. Typed twice because a PIN mistyped once
 * at creation is a room nobody can open again without the operator.
 */
export function usePinPair() {
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const complete = FOUR_DIGITS.test(pin) && FOUR_DIGITS.test(again);
  const mismatch = again.length === 4 && pin !== again;
  return { pin, setPin, again, setAgain, ok: complete && !mismatch, mismatch };
}

export function PinPairFields({
  pair,
  idPrefix,
  autoFocus = false,
}: {
  pair: ReturnType<typeof usePinPair>;
  idPrefix: string;
  autoFocus?: boolean;
}) {
  const { t } = useT();
  return (
    <>
      <label className="mt-4 block text-sm font-semibold text-slate-700" htmlFor={`${idPrefix}-pin`}>
        {t("Choose a 4-digit PIN")}
      </label>
      <PinInput id={`${idPrefix}-pin`} value={pair.pin} onChange={pair.setPin} autoFocus={autoFocus} />
      <label className="mt-3 block text-sm font-semibold text-slate-700" htmlFor={`${idPrefix}-again`}>
        {t("Type the PIN again")}
      </label>
      <PinInput id={`${idPrefix}-again`} value={pair.again} onChange={pair.setAgain} />
      {pair.mismatch && (
        <p className="mt-2 text-sm text-rose-600">{t("The two PINs do not match.")}</p>
      )}
    </>
  );
}

/** Set the PIN of the room you are in -- for rooms that do not have one yet. */
export default function PinSetup({ onDone }: { onDone: (room: RoomOut) => void }) {
  const { t } = useT();
  const pair = usePinPair();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!pair.ok) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await setMyPin(pair.pin));
    } catch (err) {
      setError(t(err instanceof Error ? err.message : String(err)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <PinPairFields pair={pair} idPrefix="setup" autoFocus />
      <button
        type="submit"
        disabled={!pair.ok || busy}
        className="mt-4 w-full rounded-lg bg-teal-600 py-3 text-base font-bold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {busy ? t("Saving…") : t("Save PIN")}
      </button>
      {error && (
        <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
      )}
    </form>
  );
}
