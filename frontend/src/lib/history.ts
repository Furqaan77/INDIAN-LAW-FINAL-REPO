import { useSyncExternalStore } from "react";
import type { ResearchMode, ResearchResult } from "../types";

export interface ResearchEntry {
  id: string;
  question: string;
  mode: ResearchMode;
  createdAt: number;
  result: ResearchResult;
}

const STORAGE_KEY = "indianlawgpt.research-history.v1";
const MAX_ENTRIES = 50;

let cache: ResearchEntry[] | null = null;
const listeners = new Set<() => void>();

function read(): ResearchEntry[] {
  if (cache) return cache;
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    cache = Array.isArray(parsed) ? parsed : [];
  } catch {
    cache = [];
  }
  return cache;
}

function write(entries: ResearchEntry[]) {
  cache = entries;
  // Storage can be full or unavailable (private mode); history is a convenience, so
  // drop the oldest entries and retry rather than failing the research itself.
  for (let kept = entries; kept.length; kept = kept.slice(0, Math.floor(kept.length / 2))) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(kept));
      break;
    } catch {
      if (kept.length === 1) break;
    }
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) {
      cache = null;
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export const history = {
  get: (id: string) => read().find((entry) => entry.id === id),
  save: (entry: ResearchEntry) =>
    write([entry, ...read().filter((existing) => existing.id !== entry.id)].slice(0, MAX_ENTRIES)),
  remove: (id: string) => write(read().filter((entry) => entry.id !== id)),
  clear: () => write([]),
};

export function useResearchHistory(): ResearchEntry[] {
  return useSyncExternalStore(subscribe, read, () => []);
}

export function newResearchId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 12);
}

export function groupByDay(entries: ResearchEntry[]): { label: string; entries: ResearchEntry[] }[] {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const today = startOfToday.getTime();
  const yesterday = today - 86_400_000;
  const week = today - 6 * 86_400_000;

  const groups = new Map<string, ResearchEntry[]>();
  for (const entry of entries) {
    const label =
      entry.createdAt >= today
        ? "Today"
        : entry.createdAt >= yesterday
          ? "Yesterday"
          : entry.createdAt >= week
            ? "Earlier this week"
            : "Older";
    groups.set(label, [...(groups.get(label) ?? []), entry]);
  }
  return [...groups].map(([label, grouped]) => ({ label, entries: grouped }));
}
