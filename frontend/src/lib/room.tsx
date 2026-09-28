import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

/**
 * Which room this browser is in, and the operator's passphrase if entered.
 *
 * Both are read by apiFetch on every request rather than threaded through
 * props, because every call a clinician makes has to carry the room -- a call
 * that forgets it falls back to the operator's view of everyone's data.
 *
 * The room lives in localStorage so it survives closing the tab: a clinician
 * who comes back tomorrow should land in their room, not at the door. The
 * passphrase lives in sessionStorage, so it goes when the tab does. Both are
 * wrapped in try/catch because storage can be missing or throw (private
 * windows, blocked site data).
 */

export type Room = { id: number; name: string };

const ROOM_KEY = "spine.room";
const ADMIN_KEY = "spine.adminKey";

export function readRoom(): Room | null {
  try {
    const raw = window.localStorage.getItem(ROOM_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Room;
    return typeof parsed?.id === "number" && typeof parsed?.name === "string"
      ? parsed
      : null;
  } catch {
    return null;
  }
}

export function writeRoom(room: Room | null): void {
  try {
    if (room) window.localStorage.setItem(ROOM_KEY, JSON.stringify(room));
    else window.localStorage.removeItem(ROOM_KEY);
  } catch {
    /* the room just will not survive a reload */
  }
}

export function readAdminKey(): string | null {
  try {
    return window.sessionStorage.getItem(ADMIN_KEY);
  } catch {
    return null;
  }
}

export function writeAdminKey(key: string | null): void {
  try {
    if (key) window.sessionStorage.setItem(ADMIN_KEY, key);
    else window.sessionStorage.removeItem(ADMIN_KEY);
  } catch {
    /* re-enter it next time */
  }
}

type Ctx = {
  room: Room | null;
  enter: (room: Room) => void;
  leave: () => void;
};

const RoomContext = createContext<Ctx>({ room: null, enter: () => {}, leave: () => {} });

export function RoomProvider({ children }: { children: ReactNode }) {
  const [room, setRoom] = useState<Room | null>(readRoom);
  const enter = useCallback((next: Room) => {
    writeRoom(next);
    setRoom(next);
  }, []);
  const leave = useCallback(() => {
    writeRoom(null);
    setRoom(null);
  }, []);
  return (
    <RoomContext.Provider value={{ room, enter, leave }}>{children}</RoomContext.Provider>
  );
}

export function useRoom() {
  return useContext(RoomContext);
}

/**
 * A study id as a person should read it. Ids made in a room carry a "p<n>-"
 * prefix so two rooms can both have "ca1"; the prefix is bookkeeping, and a
 * clinician who typed "ca1" should see "ca1".
 */
export function displayStudyId(id: string): string {
  return id.replace(/^p\d+-/, "");
}
