import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: Error };

/**
 * Runs `load` whenever `key` changes, aborting the previous request.
 * Pass `null` as the key to stay idle (reported as loading).
 */
export function useAsync<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    setState({ status: "loading" });
    load(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: Error) => {
        if (error.name !== "AbortError") setState({ status: "error", error });
      });
    return () => controller.abort();
    // `load` is intentionally keyed by `key`, so callers can pass inline closures.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
