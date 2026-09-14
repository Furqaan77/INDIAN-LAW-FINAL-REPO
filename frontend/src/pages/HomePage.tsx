import { ArrowRight, ArrowUpRight } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CommandBar } from "../components/research/CommandBar";
import { SourceGlyph } from "../components/primitives";
import { useCorpusStats } from "../hooks/useCorpusStats";
import { api } from "../lib/api";
import { actShortName, formatNumber } from "../lib/format";
import { destinationFor, type ModeId } from "../lib/modes";
import type { CorpusStats, MappedAct } from "../types";

const EASE = [0.22, 1, 0.36, 1] as const;

const EXAMPLES: { text: string; mode: ModeId }[] = [
  { text: "Can a cheque bounce complaint proceed if the demand notice was sent late?", mode: "research" },
  { text: "Which provision governs anticipatory bail under the new criminal laws?", mode: "research" },
  { text: "How does the BNS treat cheating compared with the IPC?", mode: "research" },
  { text: "Security cheques and legally enforceable debt", mode: "cases" },
];

export function HomePage() {
  const { stats, failed } = useCorpusStats();

  useEffect(() => {
    document.title = "IndianLawGPT — Research Indian law with evidence";
  }, []);

  return (
    <div>
      <section className="mx-auto max-w-[1180px] px-5 pt-[clamp(3rem,11vh,7.5rem)] pb-20 sm:px-8">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: EASE }}
          className="max-w-[46rem]"
        >
          <p className="eyebrow">Statutes · Judgments · Verified citations</p>
          <h1 className="mt-5 font-serif text-[clamp(2.65rem,6.4vw,4.75rem)] leading-[1.01] tracking-[-0.022em] text-ink">
            Research Indian law <em className="text-accent">with evidence.</em>
          </h1>
          <p className="mt-6 max-w-[37rem] text-[17px] leading-[1.62] text-ink-2">
            IndianLawGPT searches Indian statutes and judgments, builds its analysis only from the passages it finds, and
            shows you the exact source text behind every citation — each one checked against the legal database.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.08, ease: EASE }}
          className="mt-10 max-w-[50rem]"
        >
          <CommandBar variant="hero" autoFocus />
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.25 }}
          className="mt-8 max-w-[50rem]"
        >
          <ExampleQueries />
        </motion.div>
      </section>

      {!failed && <CorpusLedger stats={stats} />}
      <MethodSection />
      <LawMapTeaser />
      <SiteFooter stats={stats} />
    </div>
  );
}

function ExampleQueries() {
  const navigate = useNavigate();
  return (
    <div>
      <p className="eyebrow">Try</p>
      <ul className="mt-3 grid gap-x-8 sm:grid-cols-2">
        {EXAMPLES.map((example) => (
          <li key={example.text} className="border-t border-rule">
            <button
              type="button"
              onClick={() => {
                const destination = destinationFor(example.mode, example.text);
                if (destination.ok) navigate(destination.to);
              }}
              className="group flex w-full items-start gap-3 py-3 text-left text-[14.5px] leading-snug text-ink-2 transition-colors hover:text-ink"
            >
              <span className="mt-[3px] w-3 shrink-0 text-center">
                <SourceGlyph type={example.mode === "cases" ? "case_law" : "statute"} />
              </span>
              <span className="flex-1">
                {example.text}
                {example.mode === "cases" && <span className="ml-2 text-[12px] text-ink-4">Case search</span>}
              </span>
              <ArrowRight
                aria-hidden
                size={14}
                className="mt-[3px] shrink-0 -translate-x-1 text-ink-4 opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100"
              />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CorpusLedger({ stats }: { stats: CorpusStats | null }) {
  const figures = stats
    ? [
        { value: stats.by_source_type.statute ?? 0, label: "Statutory sections" },
        { value: stats.acts, label: "Central Acts" },
        { value: stats.by_source_type.case_law ?? 0, label: "Judgments" },
        ...(stats.passages ? [{ value: stats.passages, label: "Indexed passages" }] : []),
      ]
    : null;

  return (
    <section aria-label="What IndianLawGPT searches" className="border-y border-rule bg-raised/60">
      <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8">
        <dl className="grid grid-cols-2 gap-y-8 lg:grid-cols-4">
          {(figures ?? Array.from({ length: 4 }, () => null)).map((figure, index) => (
            <div key={index} className="pr-6 lg:border-l lg:border-rule lg:pl-6 lg:first:border-l-0 lg:first:pl-0">
              <dt className="eyebrow">{figure ? figure.label : <span className="skeleton inline-block h-3 w-24" />}</dt>
              <dd className="mt-2 font-serif text-[2.35rem] leading-none tracking-[-0.01em] text-ink tabular-nums">
                {figure ? formatNumber(figure.value) : <span className="skeleton inline-block h-8 w-28" />}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-8 max-w-[52rem] text-[13.5px] leading-relaxed text-ink-3">
          Statutory text covers Central Acts from India Code. Case law is currently a focused collection of judgments on
          Section 138 of the Negotiable Instruments Act; answers outside the indexed material say so rather than guess.
        </p>
      </div>
    </section>
  );
}

const METHOD = [
  {
    title: "Retrieve",
    body: "Semantic search across every indexed passage, combined with keyword search over full statutes and judgments.",
  },
  {
    title: "Select",
    body: "Candidates are re-ranked and a small set of authorities is chosen, with only a few passages from any one document.",
  },
  {
    title: "Analyse",
    body: "The analysis is written only from those passages, quoting the exact text that supports each claim.",
  },
  {
    title: "Verify",
    body: "Every quote is matched to its passage and each source checked against the database. Citations that fail are removed.",
  },
];

function MethodSection() {
  return (
    <section className="mx-auto max-w-[1180px] px-5 py-20 sm:px-8">
      <div className="max-w-[40rem]">
        <p className="eyebrow">Method</p>
        <h2 className="mt-3 font-serif text-[clamp(1.9rem,3.6vw,2.6rem)] leading-[1.1] tracking-[-0.015em] text-ink">
          How every answer is built
        </h2>
      </div>
      <ol className="mt-12 grid gap-10 sm:grid-cols-2 lg:grid-cols-4 lg:gap-8">
        {METHOD.map((step, index) => (
          <li key={step.title} className="border-t border-ink pt-5">
            <span className="font-mono text-[12px] text-ink-4">0{index + 1}</span>
            <h3 className="mt-2 text-[17px] font-medium text-ink">{step.title}</h3>
            <p className="mt-2 text-[14.5px] leading-relaxed text-ink-3">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function LawMapTeaser() {
  const [acts, setActs] = useState<MappedAct[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .mappedActs(controller.signal)
      .then((response) => setActs(response.acts.filter((act) => act.direction === "successor")))
      .catch(() => setActs([]));
    return () => controller.abort();
  }, []);

  if (acts && acts.length === 0) return null;

  return (
    <section className="border-t border-rule bg-sunk/50">
      <div className="mx-auto grid max-w-[1180px] gap-12 px-5 py-20 sm:px-8 lg:grid-cols-[1fr_1.1fr] lg:items-center">
        <div>
          <p className="eyebrow">Old law → New law</p>
          <h2 className="mt-3 font-serif text-[clamp(1.9rem,3.6vw,2.6rem)] leading-[1.1] tracking-[-0.015em] text-ink">
            Trace a provision from the old codes to the new.
          </h2>
          <p className="mt-4 max-w-[34rem] text-[15.5px] leading-relaxed text-ink-2">
            Built on published section correspondences. Each match shows how closely the provisions align, with both texts
            side by side.
          </p>
          <Link
            to="/compare"
            className="group mt-7 inline-flex items-center gap-2 text-[14.5px] font-medium text-ink underline decoration-rule-strong underline-offset-[5px] transition-colors hover:decoration-accent"
          >
            Open the law map
            <ArrowUpRight aria-hidden size={15} className="transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
          </Link>
        </div>

        <ul className="divide-y divide-rule border-y border-rule">
          {(acts ?? Array.from({ length: 3 }, () => null)).map((act, index) => (
            <li key={act?.act_id ?? index} className="flex items-center gap-4 py-4">
              {act ? (
                <>
                  <span className="w-28 shrink-0 font-mono text-[13px] text-ink-3">{actShortName(act.act_id, act.act_title)}</span>
                  <span aria-hidden className="h-px flex-1 bg-rule-strong" />
                  <span className="font-serif text-[1.2rem] text-ink">
                    {actShortName(act.counterpart_act_id, act.counterpart_act_title)}
                  </span>
                  <span className="w-28 shrink-0 text-right text-[12.5px] text-ink-4 tabular-nums">
                    {formatNumber(act.mapped_sections)} sections
                  </span>
                </>
              ) : (
                <span className="skeleton h-5 w-full" />
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function SiteFooter({ stats }: { stats: CorpusStats | null }) {
  return (
    <footer className="border-t border-rule">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-3 px-5 py-8 text-[12.5px] text-ink-3 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <p>IndianLawGPT is a research aid, not legal advice. Read the full source before relying on an authority.</p>
        {stats && (
          <p className="font-mono text-[11.5px] text-ink-4">
            {stats.models.llm} · {stats.models.embedding}
          </p>
        )}
      </div>
    </footer>
  );
}
