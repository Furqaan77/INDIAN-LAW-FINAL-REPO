import { useEffect, useState } from "react";
import type { EngineKey, ResearchMode, ResearchResult, StageEvent, StageId } from "../types";
import { streamResearch } from "./api";
import { history } from "./history";

export type ResearchPhase = "running" | "complete" | "failed";

export const ENGINE_KEYS: EngineKey[] = ["claude", "qwen", "lora_qwen"];
export const DEFAULT_ENGINE: EngineKey = "claude";

export interface ResearchSnapshot {
  id: string;
  engine: EngineKey;
  question: string;
  mode: ResearchMode;
  phase: ResearchPhase;
  startedAt: number;
  stages: Partial<Record<StageId, StageEvent>>;
  result: ResearchResult | null;
  error: string | null;
}

interface Session {
  snapshot: ResearchSnapshot;
  listeners: Set<(snapshot: ResearchSnapshot) => void>;
  done: Promise<void>;
}

/**
 * In-flight research lives outside React: navigating away doesn't cancel a request
 * (the finished analysis still lands in history), and a remount — including React
 * StrictMode's double effect in development — reattaches instead of paying for a
 * second pipeline run. Sessions are keyed per research id AND answer engine.
 */
const sessions = new Map<string, Session>();
const pageListeners = new Set<() => void>();

const keyOf = (id: string, engine: EngineKey) => `${id}:${engine}`;

function notifyPage() {
  pageListeners.forEach((listener) => listener());
}

function update(session: Session, patch: Partial<ResearchSnapshot>) {
  session.snapshot = { ...session.snapshot, ...patch };
  session.listeners.forEach((listener) => listener(session.snapshot));
  notifyPage();
}

/** The frozen evidence already used for this research, so another engine answers from the identical evidence. */
function evidenceIdFor(id: string): string | null {
  for (const engine of ENGINE_KEYS) {
    const fromSession = sessions.get(keyOf(id, engine))?.snapshot.result?.evidence?.evidence_id;
    if (fromSession) return fromSession;
  }
  const entry = history.get(id);
  for (const result of Object.values(entry?.engines ?? {})) {
    if (result?.evidence?.evidence_id) return result.evidence.evidence_id;
  }
  return null;
}

function start(id: string, engine: EngineKey, question: string, mode: ResearchMode): Session {
  const session = {
    snapshot: { id, engine, question, mode, phase: "running", startedAt: Date.now(), stages: {}, result: null, error: null },
    listeners: new Set(),
  } as unknown as Session;
  sessions.set(keyOf(id, engine), session);

  session.done = streamResearch(
    question,
    mode,
    {
      onStage: (event) => update(session, { stages: { ...session.snapshot.stages, [event.stage]: event } }),
      onResult: (result) => {
        if (result.error) {
          const message = result.engine?.message ?? result.answer_markdown;
          update(session, { phase: "failed", result, error: message });
          return;
        }
        history.saveEngine(id, question, mode, engine, result);
        update(session, { phase: "complete", result });
      },
      onError: (message) => update(session, { phase: "failed", error: message }),
    },
    new AbortController().signal,
    { engine, evidenceId: evidenceIdFor(id) },
  );
  notifyPage();
  return session;
}

function snapshotFromHistory(id: string, engine: EngineKey): ResearchSnapshot | null {
  const entry = history.get(id);
  if (!entry) return null;
  // Entries saved before answer engines existed carry one untagged result; show it under the default engine.
  const legacy = !entry.engines && !entry.result.engine && engine === DEFAULT_ENGINE ? entry.result : null;
  const result = entry.engines?.[engine] ?? legacy;
  if (!result) return null;
  return {
    id,
    engine,
    question: entry.question,
    mode: entry.mode,
    phase: "complete",
    startedAt: entry.createdAt,
    stages: {},
    result,
    error: null,
  };
}

function currentSnapshot(id: string, engine: EngineKey): ResearchSnapshot | null {
  return sessions.get(keyOf(id, engine))?.snapshot ?? snapshotFromHistory(id, engine);
}

/** Every engine's run for this research (running, complete, failed or absent). */
export function useEngineRuns(id: string): Partial<Record<EngineKey, ResearchSnapshot>> {
  const read = () =>
    Object.fromEntries(ENGINE_KEYS.map((engine) => [engine, currentSnapshot(id, engine)]).filter(([, s]) => s)) as Partial<
      Record<EngineKey, ResearchSnapshot>
    >;
  const [runs, setRuns] = useState(read);
  useEffect(() => {
    const listener = () => setRuns(read());
    listener();
    pageListeners.add(listener);
    return () => {
      pageListeners.delete(listener);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  return runs;
}

/** Engines currently wanted for each research id; a queued engine that was deselected is not started. */
const wantedEngines = new Map<string, EngineKey[]>();

/**
 * Runs each selected engine that has no answer yet, one after another: the first run retrieves and freezes the
 * evidence, every later run reuses it by evidence_id. Engines that already answered or are running are left alone,
 * failed runs are not retried automatically, and engines deselected while queued are skipped.
 */
export async function ensureRuns(id: string, question: string, mode: ResearchMode, engines: EngineKey[]) {
  wantedEngines.set(id, engines);
  for (const engine of engines) {
    if (!wantedEngines.get(id)?.includes(engine)) continue;
    const existing = sessions.get(keyOf(id, engine));
    if (existing) {
      await existing.done;
      continue;
    }
    if (snapshotFromHistory(id, engine)) continue;
    if (!wantedEngines.get(id)?.includes(engine)) continue;
    await start(id, engine, question, mode).done;
  }
}

/** Runs one engine again for this research (after a failure), from the same frozen evidence. */
export function rerunEngine(id: string, engine: EngineKey, question: string, mode: ResearchMode) {
  sessions.delete(keyOf(id, engine));
  start(id, engine, question, mode);
}

/**
 * Resolves research `id` for one engine from, in order: an in-flight session, saved history, or a new
 * run of `question`. Returns `null` when there is nothing to show (unknown id, no question).
 */
export function useResearchSession(id: string, question: string | null, mode: ResearchMode, engine: EngineKey = DEFAULT_ENGINE) {
  const [snapshot, setSnapshot] = useState<ResearchSnapshot | null>(() => currentSnapshot(id, engine));
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let session = sessions.get(keyOf(id, engine));
    if (!session) {
      const saved = snapshotFromHistory(id, engine);
      if (saved) {
        setSnapshot(saved);
        return;
      }
      // An engine not yet run for this research starts on selection, using the question it was asked with.
      const known = question ?? history.get(id)?.question ?? null;
      if (!known) {
        setSnapshot(null);
        return;
      }
      session = start(id, engine, known, history.get(id)?.mode ?? mode);
    }
    setSnapshot(session.snapshot);
    const listener = (next: ResearchSnapshot) => setSnapshot(next);
    session.listeners.add(listener);
    return () => {
      session.listeners.delete(listener);
    };
  }, [id, question, mode, engine, attempt]);

  const retry = () => {
    const current = sessions.get(keyOf(id, engine))?.snapshot ?? snapshot;
    sessions.delete(keyOf(id, engine));
    if (current && !question) {
      // A failed run opened from a link without ?q= still knows its question.
      start(id, engine, current.question, current.mode);
    }
    setAttempt((n) => n + 1);
  };

  return { snapshot, retry };
}
