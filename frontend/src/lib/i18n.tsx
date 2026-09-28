import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

/**
 * Two-language UI, English strings as keys.
 *
 * The screens a clinician uses read in Vietnamese; the operator pages
 * (/admin, /models) stay in English for whoever runs the trial. Keys are the
 * English text itself, the gettext convention: a string that was never
 * translated falls back to readable English instead of an empty slot or a
 * dotted key, which matters when a hundred call sites are converted by hand
 * and one will inevitably be missed.
 *
 * Medical vocabulary is deliberately NOT translated -- condition names,
 * severity grades, Pfirrmann. Vietnamese radiologists read and report those in
 * English, and a Vietnamese rendering is both longer and a chance to shift the
 * meaning of a clinical term.
 */

export type Lang = "vi" | "en";

const STORAGE_KEY = "spine.lang";

type Vars = Record<string, string | number>;

// English -> Vietnamese. Placeholders are {name} and survive translation.
const VI: Record<string, string> = {};

export function registerVi(entries: Record<string, string>): void {
  Object.assign(VI, entries);
}

function fill(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (_, k: string) =>
    k in vars ? String(vars[k]) : `{${k}}`,
  );
}

type Ctx = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (english: string, vars?: Vars) => string;
};

const LangContext = createContext<Ctx>({
  lang: "en",
  setLang: () => {},
  t: (s, v) => fill(s, v),
});

function readStored(): Lang {
  // Storage can be missing or throw (private windows, blocked site data), so
  // the stored choice is a convenience and Vietnamese is the safe default.
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v === "en" ? "en" : "vi";
  } catch {
    return "vi";
  }
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStored);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* the choice just will not survive a reload */
    }
  }, []);

  const t = useCallback(
    (english: string, vars?: Vars) =>
      fill(lang === "vi" ? (VI[english] ?? english) : english, vars),
    [lang],
  );

  return (
    <LangContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LangContext.Provider>
  );
}

export function useT() {
  return useContext(LangContext);
}

/** VI | EN switch, styled for the teal header bars. */
export function LangToggle() {
  const { lang, setLang } = useT();
  const option = (value: Lang, label: string) => (
    <button
      type="button"
      onClick={() => setLang(value)}
      aria-pressed={lang === value}
      className={
        "px-2 py-1 text-[11px] font-semibold transition " +
        (lang === value
          ? "bg-white text-teal-700"
          : "text-white/80 hover:text-white")
      }
    >
      {label}
    </button>
  );
  return (
    <div
      role="group"
      aria-label="Language"
      className="flex overflow-hidden rounded-lg border border-white/30"
    >
      {option("vi", "VI")}
      {option("en", "EN")}
    </div>
  );
}
