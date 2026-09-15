import { Check, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import type { StageEvent, StageId } from "../../types";

type Detail = StageEvent["detail"];

interface Step {
  id: StageId;
  label: string;
  summary: (detail: Detail) => string | null;
}

const plural = (count: unknown, one: string, many: string) =>
  typeof count === "number" ? `${count} ${count === 1 ? one : many}` : null;

/** Only real pipeline actions reported by the backend — never model reasoning. */
const STEPS: Step[] = [
  { id: "semantic", label: "Searching indexed legal passages", summary: (d) => plural(d.passages, "relevant passage", "relevant passages") },
  { id: "keyword", label: "Searching statutes and judgments by keyword", summary: (d) => plural(d.documents, "keyword match", "keyword matches") },
  {
    id: "ranking",
    label: "Selecting supporting authorities",
    summary: (d) =>
      [plural(d.statutes, "statutory provision", "statutory provisions"), plural(d.judgments, "judgment", "judgments")]
        .filter(Boolean)
        .join(" · ") || null,
  },
  { id: "drafting", label: "Preparing the legal analysis", summary: () => null },
  { id: "verification", label: "Verifying each citation against its source", summary: (d) => plural(d.verified, "source verified", "sources verified") },
];

function useElapsed(startedAt: number, running: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

interface ResearchProgressProps {
  stages: Partial<Record<StageId, StageEvent>>;
  startedAt: number;
  running: boolean;
}

export function ResearchProgress({ stages, startedAt, running }: ResearchProgressProps) {
  const elapsed = useElapsed(startedAt, running);
  const activeStep = STEPS.find((step) => stages[step.id]?.status === "started");
  const draftingSince = stages.drafting?.status === "started" ? stages.drafting.at * 1000 : null;
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    setSlow(false);
    if (!draftingSince) return;
    const timer = window.setTimeout(() => setSlow(true), Math.max(0, draftingSince + 18_000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [draftingSince]);

  return (
    <section aria-labelledby="research-progress-heading" className="py-2">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="research-progress-heading" className="font-serif text-[1.65rem] leading-tight text-ink">
          Researching Indian law
        </h2>
        <span className="font-mono text-[12px] tabular-nums text-ink-4" aria-label={`Elapsed ${elapsed}`}>
          {elapsed}
        </span>
      </div>

      <ol className="mt-6 space-y-0.5">
        {STEPS.map((step, index) => {
          const event = stages[step.id];
          // Another engine already answered this question: its frozen evidence is reused, nothing is searched again.
          const reusedSearch = !event && Boolean((stages.ranking?.detail as Record<string, unknown> | undefined)?.reused)
            && (step.id === "semantic" || step.id === "keyword");
          const status = reusedSearch ? "done" : (event?.status ?? "pending");
          const summary = reusedSearch
            ? "Reused the evidence already retrieved for this question — not searched again"
            : status === "done" && event
              ? step.id === "ranking" && (event.detail as Record<string, unknown>).reused
                ? "Same evidence as the other answer engines"
                : step.summary(event.detail)
              : null;
          return (
            <motion.li
              key={step.id}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.06, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              className="flex items-start gap-3.5 py-2"
            >
              <StepMarker status={status} />
              <div className="min-w-0 flex-1">
                <p
                  className={`text-[14.5px] leading-6 transition-colors duration-300 ${
                    status === "pending" ? "text-ink-4" : status === "failed" ? "text-caution" : "text-ink"
                  }`}
                >
                  {step.label}
                </p>
                <AnimatePresence>
                  {summary && (
                    <motion.p
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      transition={{ duration: 0.3 }}
                      className="font-mono text-[11.5px] text-ink-3"
                    >
                      {summary}
                    </motion.p>
                  )}
                </AnimatePresence>
              </div>
            </motion.li>
          );
        })}
      </ol>

      <p aria-live="polite" className="sr-only">
        {activeStep ? `${activeStep.label}…` : ""}
      </p>
      <AnimatePresence>
        {slow && running && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mt-5 border-t border-rule pt-4 text-[13.5px] leading-relaxed text-ink-3"
          >
            Thorough analyses that quote several sources can take up to a minute.
          </motion.p>
        )}
      </AnimatePresence>
    </section>
  );
}

function StepMarker({ status }: { status: StageEvent["status"] | "pending" }) {
  return (
    <span aria-hidden className="relative mt-[5px] flex size-3.5 shrink-0 items-center justify-center">
      {status === "done" ? (
        <motion.span
          initial={{ scale: 0.4, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 500, damping: 30 }}
          className="flex size-3.5 items-center justify-center rounded-full bg-verify text-paper"
        >
          <Check size={9} strokeWidth={3.5} />
        </motion.span>
      ) : status === "started" ? (
        <span className="size-2 animate-breathe rounded-full bg-accent" />
      ) : status === "failed" ? (
        <X size={13} className="text-caution" strokeWidth={2.5} />
      ) : (
        <span className="size-2 rounded-full border border-rule-strong" />
      )}
    </span>
  );
}
