import { useEffect, useState } from "react";
import type { ResearchMode, ResearchResult, StageEvent, StageId } from "../types";
import { streamResearch } from "./api";
import { history } from "./history";

export type ResearchPhase = "running" | "complete" | "failed";

export interface ResearchSnapshot {
  id: string;
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
}

/**
 * In-flight research lives outside React: navigating away doesn't cancel a request
 * (the finished analysis still lands in history), and a remount — including React
 * StrictMode's double effect in development — reattaches instead of paying for a
 * second pipeline run.
 */
const sessions = new Map<string, Session>();

function update(session: Session, patch: Partial<ResearchSnapshot>) {
  session.snapshot = { ...session.snapshot, ...patch };
  session.listeners.forEach((listener) => listener(session.snapshot));
}

function start(id: string, question: string, mode: ResearchMode): Session {
  const session: Session = {
    snapshot: { id, question, mode, phase: "running", startedAt: Date.now(), stages: {}, result: null, error: null },
    listeners: new Set(),
  };
  sessions.set(id, session);

  streamResearch(
    question,
    mode,
    {
      onStage: (event) => update(session, { stages: { ...session.snapshot.stages, [event.stage]: event } }),
      onResult: (result) => {
        if (result.error) {
          update(session, { phase: "failed", result, error: result.answer_markdown });
          return;
        }
        history.save({ id, question, mode, createdAt: Date.now(), result });
        update(session, { phase: "complete", result });
      },
      onError: (message) => update(session, { phase: "failed", error: message }),
    },
    new AbortController().signal,
  );
  return session;
}

function snapshotFromHistory(id: string): ResearchSnapshot | null {
  const entry = history.get(id);
  if (!entry) return null;
  return {
    id,
    question: entry.question,
    mode: entry.mode,
    phase: "complete",
    startedAt: entry.createdAt,
    stages: {},
    result: entry.result,
    error: null,
  };
}

/**
 * Resolves research `id` from, in order: an in-flight session, saved history, or a new
 * run of `question`. Returns `null` when there is nothing to show (unknown id, no question).
 */
export function useResearchSession(id: string, question: string | null, mode: ResearchMode) {
  const [snapshot, setSnapshot] = useState<ResearchSnapshot | null>(
    () => sessions.get(id)?.snapshot ?? snapshotFromHistory(id),
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let session = sessions.get(id);
    if (!session) {
      const saved = snapshotFromHistory(id);
      if (saved) {
        setSnapshot(saved);
        return;
      }
      if (!question) {
        setSnapshot(null);
        return;
      }
      session = start(id, question, mode);
    }
    setSnapshot(session.snapshot);
    const listener = (next: ResearchSnapshot) => setSnapshot(next);
    session.listeners.add(listener);
    return () => {
      session.listeners.delete(listener);
    };
  }, [id, question, mode, attempt]);

  const retry = () => {
    const current = sessions.get(id)?.snapshot ?? snapshot;
    sessions.delete(id);
    if (current && !question) {
      // A failed run opened from a link without ?q= still knows its question.
      start(id, current.question, current.mode);
    }
    setAttempt((n) => n + 1);
  };

  return { snapshot, retry };
}
