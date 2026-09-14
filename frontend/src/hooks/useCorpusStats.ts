import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { CorpusStats } from "../types";

let cached: CorpusStats | null = null;

/** Corpus size shown on the home page; `null` while loading or if the API is unreachable. */
export function useCorpusStats(): { stats: CorpusStats | null; failed: boolean } {
  const [stats, setStats] = useState<CorpusStats | null>(cached);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (cached) return;
    const controller = new AbortController();
    api
      .stats(controller.signal)
      .then((value) => {
        cached = value;
        setStats(value);
      })
      .catch((error: Error) => {
        if (error.name !== "AbortError") setFailed(true);
      });
    return () => controller.abort();
  }, []);

  return { stats, failed };
}
