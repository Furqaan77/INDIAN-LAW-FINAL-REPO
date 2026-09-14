import { BookMarked, RotateCcw, X } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CopyButton } from "../components/CopyButton";
import { Drawer } from "../components/Drawer";
import { EvidenceRail, EvidenceRailPlaceholder } from "../components/evidence/EvidenceRail";
import { Button, IconButton, StatePanel } from "../components/primitives";
import { AnswerView } from "../components/research/AnswerView";
import { CommandBar } from "../components/research/CommandBar";
import { ResearchProgress } from "../components/research/ResearchProgress";
import { VerificationNote } from "../components/research/VerificationNote";
import { useHotkey } from "../hooks/useHotkey";
import { BREAKPOINTS, useMediaQuery } from "../hooks/useMediaQuery";
import { formatCitation } from "../lib/citation";
import { relativeTime } from "../lib/format";
import { useResearchSession, type ResearchSnapshot } from "../lib/researchSessions";
import type { ResearchMode, ResearchResult } from "../types";

export function ResearchPage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const question = params.get("q");
  const mode: ResearchMode = params.get("mode") === "quick" ? "quick" : "research";
  const { snapshot, retry } = useResearchSession(id, question, mode);
  const isDesktop = useMediaQuery(BREAKPOINTS.lg);
  const [activeNumber, setActiveNumber] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    setActiveNumber(null);
    setSheetOpen(false);
  }, [id]);

  useEffect(() => {
    if (snapshot?.question) document.title = `${snapshot.question} — IndianLawGPT`;
  }, [snapshot?.question]);

  const selectCitation = useCallback(
    (number: number) => {
      setActiveNumber(number);
      if (!isDesktop) setSheetOpen(true);
    },
    [isDesktop],
  );

  useHotkey("escape", () => setActiveNumber(null), { enabled: activeNumber !== null && !sheetOpen });

  if (!snapshot) {
    return (
      <div className="px-5">
        <StatePanel
          title="This research isn’t available"
          action={
            <Link to="/" className="rounded-md bg-ink px-4 py-2 text-sm text-paper hover:bg-ink-2">
              Start new research
            </Link>
          }
        >
          Research history is kept on the device where it was run, so this link can’t be opened here.
        </StatePanel>
      </div>
    );
  }

  const result = snapshot.phase === "complete" ? snapshot.result : null;
  const running = snapshot.phase === "running";

  return (
    <div className={isDesktop && (result || running) ? "grid grid-cols-[minmax(0,1fr)_clamp(340px,31vw,450px)]" : ""}>
      <div className="min-w-0 px-5 pt-9 pb-24 sm:px-10 lg:px-14 lg:pt-12">
        <div className="mx-auto max-w-[44rem]">
          <QuestionHeader snapshot={snapshot} />

          <div className="mt-10">
            {running && <ResearchProgress stages={snapshot.stages} startedAt={snapshot.startedAt} running />}

            {snapshot.phase === "failed" && (
              <StatePanel
                tone="error"
                title="The research couldn’t be completed"
                action={
                  <Button variant="primary" onClick={retry}>
                    <RotateCcw aria-hidden size={15} />
                    Try again
                  </Button>
                }
              >
                {snapshot.error ?? "Something went wrong while researching this question."}
              </StatePanel>
            )}

            {result && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              >
                <AnswerView
                  markdown={result.answer_markdown}
                  citations={result.citations}
                  activeNumber={activeNumber}
                  onSelectCitation={selectCitation}
                />
                <div className="mt-12 border-t border-rule pt-5">
                  <VerificationNote result={result} />
                </div>
                <AnswerActions result={result} />
              </motion.div>
            )}
          </div>

          {result && (
            <section aria-label="Research another question" className="mt-16">
              <p className="eyebrow mb-3">Research another question</p>
              <CommandBar variant="compact" modes={["research", "quick"]} initialMode={mode} />
            </section>
          )}
        </div>
      </div>

      {isDesktop && (result || running) && (
        <aside aria-label="Evidence" className="sticky top-14 h-[calc(100dvh-3.5rem)] border-l border-rule bg-raised/40">
          {result ? (
            <EvidenceRail result={result} activeNumber={activeNumber} onSelect={setActiveNumber} />
          ) : (
            <EvidenceRailPlaceholder />
          )}
        </aside>
      )}

      {!isDesktop && result && (
        <>
          <div
            className="sticky bottom-0 z-30 border-t border-rule bg-paper/90 px-5 pt-3 backdrop-blur-md"
            style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}
          >
            <button
              type="button"
              onClick={() => setSheetOpen(true)}
              className="flex h-11 w-full items-center justify-between rounded-lg border border-rule-strong bg-raised px-4 text-[14px] text-ink shadow-lift"
            >
              <span className="flex items-center gap-2">
                <BookMarked aria-hidden size={16} strokeWidth={1.75} />
                Evidence
              </span>
              <span className="text-ink-3">
                {result.citations.length} {result.citations.length === 1 ? "source" : "sources"}
              </span>
            </button>
          </div>
          <Drawer open={sheetOpen} onClose={() => setSheetOpen(false)} side="bottom" label="Evidence">
            <div className="h-[80dvh]">
              <EvidenceRail
                result={result}
                activeNumber={activeNumber}
                onSelect={setActiveNumber}
                headerAction={
                  <IconButton label="Close evidence" size="sm" onClick={() => setSheetOpen(false)}>
                    <X aria-hidden size={16} />
                  </IconButton>
                }
              />
            </div>
          </Drawer>
        </>
      )}
    </div>
  );
}

function QuestionHeader({ snapshot }: { snapshot: ResearchSnapshot }) {
  return (
    <header>
      <p className="flex items-center gap-2">
        <span className="eyebrow text-accent">{snapshot.mode === "quick" ? "Quick answer" : "Legal research"}</span>
        <span aria-hidden className="text-ink-4">
          ·
        </span>
        <time dateTime={new Date(snapshot.startedAt).toISOString()} className="text-[12.5px] text-ink-3">
          {relativeTime(snapshot.startedAt)}
        </time>
      </p>
      <h1 className="mt-3 font-serif text-[clamp(1.75rem,3.3vw,2.35rem)] leading-[1.16] tracking-[-0.012em] text-balance text-ink">
        {snapshot.question}
      </h1>
    </header>
  );
}

function AnswerActions({ result }: { result: ResearchResult }) {
  const plainText = () => {
    const sources = result.citations.map((citation) => `[${citation.number}] ${formatCitation(citation.title, citation.document)}`);
    return [result.question, "", result.answer_markdown, ...(sources.length ? ["", "Sources", ...sources] : [])].join("\n");
  };

  return (
    <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
      <CopyButton text={plainText} label="Copy analysis with sources" showLabel className="-ml-2" />
      <span className="ml-auto font-mono text-[11px] text-ink-4">{result.models.llm}</span>
    </div>
  );
}
