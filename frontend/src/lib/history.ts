import { useCallback, useState } from "react";

interface History<T> {
  state: T;
  /** Push a new state, discarding any redo entries ahead of the cursor. */
  set: (next: T) => void;
  /** Replace the whole history with a single entry (e.g. on load / Run AI). */
  reset: (value: T) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

/**
 * A minimal undo/redo stack over an immutable value. Used for grade edits so a
 * doctor can revert severity changes before saving.
 */
export function useHistory<T>(initial: T): History<T> {
  const [past, setPast] = useState<T[]>([]);
  const [present, setPresent] = useState<T>(initial);
  const [future, setFuture] = useState<T[]>([]);

  const set = useCallback(
    (next: T) => {
      setPast((p) => [...p, present]);
      setPresent(next);
      setFuture([]);
    },
    [present],
  );

  const reset = useCallback((value: T) => {
    setPast([]);
    setPresent(value);
    setFuture([]);
  }, []);

  const undo = useCallback(() => {
    setPast((p) => {
      if (p.length === 0) return p;
      const previous = p[p.length - 1];
      setFuture((f) => [present, ...f]);
      setPresent(previous);
      return p.slice(0, -1);
    });
  }, [present]);

  const redo = useCallback(() => {
    setFuture((f) => {
      if (f.length === 0) return f;
      const next = f[0];
      setPast((p) => [...p, present]);
      setPresent(next);
      return f.slice(1);
    });
  }, [present]);

  return {
    state: present,
    set,
    reset,
    undo,
    redo,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
  };
}
