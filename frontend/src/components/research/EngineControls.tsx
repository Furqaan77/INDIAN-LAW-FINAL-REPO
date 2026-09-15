import { ArrowRight, ChevronDown } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { ENGINE_ORDER } from "../../lib/engines";
import type { ResearchSnapshot } from "../../lib/researchSessions";
import type { EngineKey, EngineStatus, OutputStatus, ResearchResult } from "../../types";

/** Static engine descriptions so the controls render before /api/engines answers. */
export const ENGINE_LABELS: Record<
  EngineKey,
  { label: string; model: string; description: string; role: string; runtime: string; experimental: boolean }
> = {
  claude: {
    label: "Claude API",
    model: "Claude + IndianLawGPT RAG",
    description: "Claude API with the IndianLawGPT evidence pipeline.",
    role: "Teacher / reference model",
    runtime: "Anthropic API",
    experimental: false,
  },
  qwen: {
    label: "Plain Qwen",
    model: "Qwen3 1.7B + RAG",
    description: "Base Qwen3 1.7B using the same IndianLawGPT evidence.",
    role: "Base local model (control)",
    runtime: "Ollama (local)",
    experimental: false,
  },
  lora_qwen: {
    label: "LoRA Qwen",
    model: "Fine-tuned Qwen3 1.7B + RAG",
    description: "Experimental LoRA Qwen using the same IndianLawGPT evidence.",
    role: "Experimental fine-tuned student",
    runtime: "MLX local service",
    experimental: true,
  },
};

const STATUS_TONE: Record<OutputStatus, string> = {
  VALID: "border-verify/40 bg-verify-wash text-verify",
  MALFORMED: "border-caution/40 bg-caution-wash text-caution",
  TRUNCATED: "border-caution/40 bg-caution-wash text-caution",
  FAILED: "border-accent/40 bg-accent-wash text-accent-ink",
};

let statusCache: Partial<Record<EngineKey, EngineStatus>> | null = null;

export function useEngineStatus() {
  const [statuses, setStatuses] = useState<Partial<Record<EngineKey, EngineStatus>>>(statusCache ?? {});
  useEffect(() => {
    const controller = new AbortController();
    api
      .engines(controller.signal)
      .then(({ engines }) => {
        statusCache = Object.fromEntries(engines.map((engine) => [engine.key, engine]));
        setStatuses(statusCache);
      })
      .catch(() => undefined); // availability hints are optional; a run still reports its own failure
    return () => controller.abort();
  }, []);
  return statuses;
}

export function ExperimentalTag() {
  return (
    <span className="rounded-[4px] border border-caution/50 bg-caution-wash px-1 py-px text-[9.5px] font-semibold tracking-[0.08em] text-caution">
      EXPERIMENTAL
    </span>
  );
}

function engineDot(run: ResearchSnapshot | undefined, status: EngineStatus | undefined) {
  if (run?.phase === "running") return { className: "bg-ink-3 animate-pulse", label: "answering" };
  if (run?.phase === "complete") return { className: "bg-verify", label: "answered" };
  if (run?.phase === "failed") return { className: "bg-accent", label: "failed" };
  if (status && !status.available) return { className: "border border-accent bg-transparent", label: "unavailable" };
  if (status?.available) return { className: "border border-verify bg-transparent", label: "available" };
  return { className: "border border-rule-strong bg-transparent", label: "not run" };
}

/**
 * Multi-select answer engines: any combination of Claude API, Plain Qwen and LoRA Qwen (at least one).
 * Used in the question box and on the research page.
 */
export function EngineToggleGroup({
  selected,
  onChange,
  runs,
  size = "md",
}: {
  selected: EngineKey[];
  onChange: (engines: EngineKey[]) => void;
  runs?: Partial<Record<EngineKey, ResearchSnapshot>>;
  size?: "sm" | "md";
}) {
  const statuses = useEngineStatus();
  const height = size === "sm" ? "h-8 text-[12.5px]" : "h-9 text-[13.5px]";
  const toggle = (key: EngineKey) => {
    if (selected.includes(key)) {
      if (selected.length > 1) onChange(selected.filter((engine) => engine !== key));
    } else {
      onChange(ENGINE_ORDER.filter((engine) => engine === key || selected.includes(engine)));
    }
  };
  const all = selected.length === ENGINE_ORDER.length;

  return (
    <div role="group" aria-label="Answer engines" className="flex flex-wrap items-center gap-1.5">
      {ENGINE_ORDER.map((key) => {
        const on = selected.includes(key);
        const dot = engineDot(runs?.[key], statuses[key]);
        return (
          <button
            key={key}
            type="button"
            aria-pressed={on}
            title={`${ENGINE_LABELS[key].description}${statuses[key] ? ` — ${statuses[key]!.detail}` : ""}`}
            onClick={() => toggle(key)}
            className={`inline-flex items-center gap-2 rounded-full border px-3 transition-colors focus-visible:outline-2 focus-visible:outline-accent ${height} ${
              on ? "border-ink bg-ink text-paper" : "border-rule-strong bg-paper text-ink-2 hover:border-ink-3 hover:text-ink"
            }`}
          >
            <span aria-hidden className={`size-2 rounded-full ${dot.className}`} />
            {ENGINE_LABELS[key].label}
            {ENGINE_LABELS[key].experimental && <ExperimentalTag />}
            <span className="sr-only">({dot.label})</span>
          </button>
        );
      })}
      <button
        type="button"
        onClick={() => onChange(ENGINE_ORDER)}
        disabled={all}
        className={`rounded-full px-2.5 text-ink-3 underline decoration-rule-strong underline-offset-4 hover:text-ink disabled:no-underline disabled:opacity-50 ${height}`}
      >
        All 3
      </button>
    </div>
  );
}

/** Question → retrieval → frozen evidence → selected engines → verification, with the real evidence id and source count. */
function EvidenceFlow({ runs, selected }: { runs: Partial<Record<EngineKey, ResearchSnapshot>>; selected: EngineKey[] }) {
  const answered = ENGINE_ORDER.map((key) => runs[key]?.result).filter((result): result is ResearchResult => Boolean(result));
  const frozen = answered.find((result) => result.evidence?.evidence_id);
  const retrieving = !frozen && ENGINE_ORDER.some((key) => runs[key]?.phase === "running");
  const sources = frozen?.retrieved_documents.length ?? 0;
  const steps = [
    { label: "Question", detail: null },
    { label: "IndianLawGPT retrieval", detail: "hybrid · references · rerank" },
    {
      label: frozen ? `${sources} evidence ${sources === 1 ? "source" : "sources"}` : retrieving ? "Retrieving evidence…" : "Evidence",
      detail: frozen ? `frozen · ${frozen.evidence!.evidence_id}` : null,
    },
    { label: selected.map((key) => ENGINE_LABELS[key].label).join(" · "), detail: selected.length > 1 ? "same evidence" : "answer engine" },
    { label: "Citation verification", detail: "deterministic" },
  ];
  return (
    <ol aria-label="How this answer is produced" className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-[12.5px]">
      {steps.map((step, index) => (
        <Fragment key={index}>
          {index > 0 && <ArrowRight aria-hidden size={13} className="shrink-0 text-ink-4" />}
          <li className={`rounded-md border px-2 py-1 ${index === 2 && frozen ? "border-verify/40 bg-verify-wash/60" : "border-rule bg-raised"}`}>
            <span className="text-ink">{step.label}</span>
            {step.detail && <span className="ml-1.5 font-mono text-[10.5px] text-ink-3">{step.detail}</span>}
          </li>
        </Fragment>
      ))}
    </ol>
  );
}

export function EngineSelector({
  selected,
  runs,
  onChange,
}: {
  selected: EngineKey[];
  runs: Partial<Record<EngineKey, ResearchSnapshot>>;
  onChange: (engines: EngineKey[]) => void;
}) {
  return (
    <section aria-label="Answer engines" className="mt-7 rounded-lg border border-rule bg-sunk/40 p-4">
      <EvidenceFlow runs={runs} selected={selected} />
      <p className="eyebrow mt-4 mb-2">Answer engines — select one, two or all three</p>
      <EngineToggleGroup selected={selected} onChange={onChange} runs={runs} />
      <p className="mt-2 text-[12px] text-ink-3">
        Retrieval runs once; every selected engine answers from the same frozen evidence, one after another. Adding an
        engine answers this question again from that evidence. If an engine is unavailable, no other model answers for it.
      </p>
    </section>
  );
}

export function OutputStatusChip({ status }: { status: OutputStatus }) {
  return (
    <span
      title="Structured-output check of the model's reply (VALID, MALFORMED, TRUNCATED or FAILED)"
      className={`rounded border px-1.5 py-0.5 font-mono text-[10.5px] tracking-wide ${STATUS_TONE[status]}`}
    >
      {status}
    </span>
  );
}

export function EngineAnswerHeader({ result }: { result: ResearchResult }) {
  const engine = result.engine;
  if (!engine) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center gap-2 border-b border-rule pb-3">
      <span className="text-[13px] font-medium text-ink">{ENGINE_LABELS[engine.key]?.label ?? engine.label}</span>
      <span className="font-mono text-[12px] text-ink-3">{engine.subtitle}</span>
      {engine.experimental && <ExperimentalTag />}
      <span className="ml-auto">
        <OutputStatusChip status={engine.output_status} />
      </span>
      {engine.adapter_label && (
        <p className="w-full text-[12px] text-ink-3">{engine.adapter_label} — a research experiment, not a production model.</p>
      )}
      <RecoveryNote result={result} />
    </div>
  );
}

/** Says plainly when the shown answer came from a malformed reply, so a MALFORMED status is never confusing. */
export function RecoveryNote({ result }: { result: ResearchResult }) {
  const engine = result.engine;
  if (!engine || (!engine.answer_recovered && !engine.raw_output_shown)) return null;
  return (
    <p className="w-full rounded-md bg-caution-wash/60 px-2 py-1 text-[12px] text-caution">
      {engine.raw_output_shown
        ? "The model's reply was not valid structured output and no answer could be extracted — its raw output is shown unedited."
        : "The model's reply was not valid structured output; the answer text below was recovered from it. Citations were still checked by the verifier."}
    </p>
  );
}

export const seconds = (value: number | null | undefined) => (value == null ? "—" : `${value.toFixed(1)} s`);

export function ModelDetails({ result }: { result: ResearchResult }) {
  const engine = result.engine;
  if (!engine) return null;
  const fallback = ENGINE_LABELS[engine.key];
  const rows: [string, string][] = [
    ["Engine", engine.label],
    ["Model", engine.model],
    ["Role", engine.role ?? fallback?.role ?? "—"],
    ["Provider / runtime", engine.runtime ?? fallback?.runtime ?? engine.provider],
    ["Adapter", engine.adapter ? `${engine.adapter}${engine.adapter_label ? ` (${engine.adapter_label})` : ""}` : "None"],
    ["Status", engine.experimental ? "Experimental" : "Operational"],
    ["Retrieval", engine.rag ? "IndianLawGPT RAG" : "None"],
    ["Evidence", `${engine.evidence_id ?? "—"}${engine.evidence_reused ? " (reused, same as other engines)" : " (retrieved for this answer)"}`],
    ["Retrieved sources", String(engine.retrieved_sources ?? result.retrieved_documents.length)],
    ["Generation time", seconds(engine.generation_s)],
    ["Total time", seconds(engine.total_s)],
    ["Citations", String(engine.citation_count ?? result.citations.length)],
    ["Verified citations", String(engine.verified_citations ?? result.verified_count)],
    ["Retries", String(engine.retry_count)],
    [
      "Output status",
      engine.first_output_status && engine.first_output_status !== engine.output_status
        ? `${engine.output_status} (first attempt ${engine.first_output_status})`
        : engine.output_status,
    ],
  ];
  return (
    <details className="group mt-6 rounded-lg border border-rule">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-[13px] text-ink-2 hover:text-ink [&::-webkit-details-marker]:hidden">
        Model details
        <ChevronDown aria-hidden size={15} className="transition-transform group-open:rotate-180" />
      </summary>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-1.5 border-t border-rule px-4 py-3 text-[12.5px]">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-ink-3">{label}</dt>
            <dd className="font-mono break-words text-ink-2 tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/** One row per selected engine: output status, verified/cited, rejected quotations, retries, time; confirms identical evidence. */
export function EngineComparison({ runs, selected }: { runs: Partial<Record<EngineKey, ResearchSnapshot>>; selected: EngineKey[] }) {
  if (selected.length < 2) return null;
  const evidenceIds = new Set(selected.map((key) => runs[key]?.result?.evidence?.evidence_id).filter(Boolean));

  return (
    <section aria-label="Engine comparison" className="mt-6 overflow-x-auto">
      <table className="w-full min-w-[34rem] text-left text-[12.5px] tabular-nums">
        <thead className="text-ink-3">
          <tr className="border-b border-rule">
            <th className="py-1.5 pr-4 font-normal">Engine</th>
            <th className="py-1.5 pr-4 font-normal">Output</th>
            <th className="py-1.5 pr-4 font-normal">Verified / cited</th>
            <th className="py-1.5 pr-4 font-normal">Rejected quotations</th>
            <th className="py-1.5 pr-4 font-normal">Retries</th>
            <th className="py-1.5 font-normal">Total time</th>
          </tr>
        </thead>
        <tbody>
          {selected.map((key) => {
            const run = runs[key];
            const result = run?.result;
            const info = result?.engine;
            return (
              <tr key={key} className="border-b border-rule">
                <td className="py-1.5 pr-4 text-ink">{ENGINE_LABELS[key].label}</td>
                <td className="py-1.5 pr-4">
                  {!run ? (
                    <span className="text-ink-4">queued</span>
                  ) : run.phase === "running" ? (
                    <span className="text-ink-3">answering…</span>
                  ) : (
                    <OutputStatusChip status={info?.output_status ?? "FAILED"} />
                  )}
                </td>
                <td className="py-1.5 pr-4 font-mono">{info ? `${info.verified_citations ?? 0} / ${info.citation_count ?? 0}` : "—"}</td>
                <td className="py-1.5 pr-4 font-mono">{result?.citation_check ? result.citation_check.rejected : "—"}</td>
                <td className="py-1.5 pr-4 font-mono">{info ? info.retry_count : "—"}</td>
                <td className="py-1.5 font-mono">{seconds(info?.total_s)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[12px] text-ink-3">
        {evidenceIds.size === 1
          ? `Identical frozen evidence for every engine (${[...evidenceIds][0]}).`
          : evidenceIds.size > 1
            ? "Warning: these answers were produced from different evidence."
            : "Evidence is retrieved once, by the first engine, then shared."}
      </p>
    </section>
  );
}
