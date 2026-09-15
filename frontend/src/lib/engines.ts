import type { EngineKey } from "../types";

/** Display order of the answer engines everywhere in the UI. */
export const ENGINE_ORDER: EngineKey[] = ["claude", "qwen", "lora_qwen"];
export const DEFAULT_ENGINES: EngineKey[] = ["claude"];

const STORAGE_KEY = "indianlawgpt.engines.v1";

export function normalizeEngines(values: readonly string[]): EngineKey[] {
  const wanted = new Set(values);
  return ENGINE_ORDER.filter((key) => wanted.has(key));
}

/** Parses the `engines` URL parameter, e.g. "claude,lora_qwen". */
export function parseEnginesParam(value: string | null): EngineKey[] {
  return value ? normalizeEngines(value.split(",").map((part) => part.trim())) : [];
}

/** The engines last chosen in the question box (a per-browser convenience). */
export function loadEngineSelection(): EngineKey[] {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    const engines = Array.isArray(stored) ? normalizeEngines(stored) : [];
    return engines.length ? engines : DEFAULT_ENGINES;
  } catch {
    return DEFAULT_ENGINES;
  }
}

export function saveEngineSelection(engines: EngineKey[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(engines));
  } catch {
    // Storage unavailable (private mode): the selection simply isn't remembered.
  }
}
