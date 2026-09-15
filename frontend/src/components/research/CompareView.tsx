import { BookMarked, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ResearchSnapshot } from "../../lib/researchSessions";
import type { EngineKey, StageId } from "../../types";
import { Drawer } from "../Drawer";
import { EvidenceRail } from "../evidence/EvidenceRail";
import { Button, IconButton } from "../primitives";
import { AnswerView } from "./AnswerView";
import { ENGINE_LABELS, ExperimentalTag, ModelDetails, OutputStatusChip, RecoveryNote, seconds } from "./EngineControls";
import { VerificationNote } from "./VerificationNote";

const STAGE_LABEL: Record<StageId, string> = {
  semantic: "Retrieving evidence",
  keyword: "Retrieving evidence",
  search: "Retrieving evidence",
  ranking: "Selecting evidence",
  drafting: "Generating the answer",
  verification: "Verifying citations",
};

function useElapsed(startedAt: number, running: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  return Math.max(0, Math.round((now - startedAt) / 1000));
}

function RunningState({ run }: { run: ResearchSnapshot }) {
  const elapsed = useElapsed(run.startedAt, true);
  const latest = Object.values(run.stages).sort((a, b) => (a!.at ?? 0) - (b!.at ?? 0)).pop();
  const reused = Boolean((run.stages.ranking?.detail as Record<string, unknown> | undefined)?.reused);
  const stage = latest ? (latest.stage === "ranking" && reused ? "Using the same frozen evidence" : STAGE_LABEL[latest.stage]) : "Starting";
  return (
    <div className="space-y-3" aria-live="polite">
      <p className="flex items-center gap-2 text-[14px] text-ink-2">
        <span aria-hidden className="size-2 animate-breathe rounded-full bg-accent" />
        {stage}…
        <span className="ml-auto font-mono text-[12px] text-ink-4 tabular-nums">{elapsed}s</span>
      </p>
      {reused && <p className="text-[12.5px] text-ink-3">Reused the evidence already retrieved for this question — not searched again.</p>}
      <div className="space-y-2.5" aria-hidden>
        {[92, 86, 90, 60].map((width, index) => (
          <div key={index} className="skeleton h-3.5" style={{ width: `${width}%` }} />
        ))}
      </div>
    </div>
  );
}

function EngineColumn({
  engine,
  run,
  waitingFor,
  onRetry,
  onOpenEvidence,
}: {
  engine: EngineKey;
  run: ResearchSnapshot | undefined;
  waitingFor: EngineKey | null;
  onRetry: () => void;
  onOpenEvidence: (number: number | null) => void;
}) {
  const label = ENGINE_LABELS[engine];
  const result = run?.phase === "complete" ? run.result : null;
  const failedEngine = run?.phase === "failed" && run.result?.error === "generation";

  return (
    <article aria-label={`${label.label} answer`} data-engine={engine} className="flex min-w-0 flex-col rounded-xl border border-rule bg-raised">
      <header className="flex flex-wrap items-center gap-2 border-b border-rule px-4 py-3">
        <h2 className="text-[15px] font-medium text-ink">{label.label}</h2>
        {label.experimental && <ExperimentalTag />}
        <span className="ml-auto">
          {result?.engine ? (
            <OutputStatusChip status={result.engine.output_status} />
          ) : run?.phase === "failed" ? (
            <OutputStatusChip status="FAILED" />
          ) : (
            <span className="font-mono text-[10.5px] text-ink-4">{run ? "ANSWERING" : "QUEUED"}</span>
          )}
        </span>
        <p className="w-full font-mono text-[11px] text-ink-3">{result?.engine?.subtitle ?? label.model}</p>
        {result && <RecoveryNote result={result} />}
      </header>

      <div className="flex flex-1 flex-col px-4 py-4">
        {!run && (
          <p className="text-[13.5px] leading-relaxed text-ink-3">
            {waitingFor
              ? `Queued — answers after ${ENGINE_LABELS[waitingFor].label}, from the same frozen evidence.`
              : "Starting…"}
          </p>
        )}

        {run?.phase === "running" && <RunningState run={run} />}

        {run?.phase === "failed" && (
          <div role="alert" className="rounded-lg border border-accent/30 bg-accent-wash/40 p-4">
            <p className="text-[15px] font-medium text-ink">{failedEngine ? "Engine unavailable" : "This answer couldn’t be completed"}</p>
            <p className="mt-1 text-[13.5px] text-ink-2">{run.error ?? "Something went wrong."}</p>
            {failedEngine && (
              <p className="mt-2 text-[12.5px] text-ink-3">No other model was used — IndianLawGPT never falls back to a different engine.</p>
            )}
            <Button variant="primary" size="sm" onClick={onRetry} className="mt-3">
              <RotateCcw aria-hidden size={14} />
              Try again
            </Button>
          </div>
        )}

        {result && (
          <>
            <div className="min-w-0 text-[15px]">
              <AnswerView markdown={result.answer_markdown} citations={result.citations} activeNumber={null} onSelectCitation={onOpenEvidence} />
            </div>
            <div className="mt-6 border-t border-rule pt-4">
              <VerificationNote result={result} />
            </div>
            <button
              type="button"
              onClick={() => onOpenEvidence(null)}
              className="mt-4 flex h-10 w-full items-center justify-between rounded-lg border border-rule-strong bg-paper px-3 text-[13.5px] text-ink transition-colors hover:border-ink-3"
            >
              <span className="flex items-center gap-2">
                <BookMarked aria-hidden size={15} strokeWidth={1.75} />
                Evidence
              </span>
              <span className="text-ink-3">
                {result.citations.length} cited · {result.retrieved_documents.length} retrieved · {seconds(result.engine?.total_s)}
              </span>
            </button>
            <ModelDetails result={result} />
          </>
        )}
      </div>
    </article>
  );
}

/** Side-by-side answers from the selected engines, all produced from the same frozen evidence. */
export function CompareColumns({
  selected,
  runs,
  onRetry,
}: {
  selected: EngineKey[];
  runs: Partial<Record<EngineKey, ResearchSnapshot>>;
  onRetry: (engine: EngineKey) => void;
}) {
  const [drawer, setDrawer] = useState<{ engine: EngineKey; number: number | null } | null>(null);
  const drawerResult = drawer ? runs[drawer.engine]?.result : null;
  const grid = selected.length >= 3 ? "lg:grid-cols-2 xl:grid-cols-3" : "md:grid-cols-2";

  return (
    <>
      <div className={`mt-8 grid items-start gap-5 ${grid}`}>
        {selected.map((engine, index) => {
          const waitingFor =
            selected.slice(0, index).find((previous) => !runs[previous] || runs[previous]?.phase === "running") ?? null;
          return (
            <EngineColumn
              key={engine}
              engine={engine}
              run={runs[engine]}
              waitingFor={waitingFor}
              onRetry={() => onRetry(engine)}
              onOpenEvidence={(number) => setDrawer({ engine, number })}
            />
          );
        })}
      </div>

      <Drawer open={Boolean(drawer && drawerResult)} onClose={() => setDrawer(null)} side="right" label="Evidence">
        {drawer && drawerResult && (
          <div className="flex h-full min-h-0 flex-col">
            <p className="border-b border-rule px-5 py-2 text-[12px] text-ink-3">
              Evidence as cited by <span className="font-medium text-ink">{ENGINE_LABELS[drawer.engine].label}</span>
            </p>
            <div className="min-h-0 flex-1">
              <EvidenceRail
                result={drawerResult}
                activeNumber={drawer.number}
                onSelect={(number) => setDrawer({ engine: drawer.engine, number })}
                headerAction={
                  <IconButton label="Close evidence" size="sm" onClick={() => setDrawer(null)}>
                    <X aria-hidden size={16} />
                  </IconButton>
                }
              />
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
}
