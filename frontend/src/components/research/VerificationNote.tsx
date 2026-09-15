import { ChevronRight, CircleAlert, CircleCheck, CircleX, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { ResearchResult } from "../../types";

function Row({ tone, children }: { tone: "ok" | "warn" | "bad" | "neutral"; children: ReactNode }) {
  const icon =
    tone === "ok" ? (
      <CircleCheck aria-hidden size={15} strokeWidth={2} className="mt-0.5 shrink-0 text-verify" />
    ) : tone === "bad" ? (
      <CircleX aria-hidden size={15} strokeWidth={2} className="mt-0.5 shrink-0 text-accent" />
    ) : (
      <CircleAlert aria-hidden size={15} strokeWidth={2} className={`mt-0.5 shrink-0 ${tone === "warn" ? "text-caution" : "text-ink-4"}`} />
    );
  return (
    <li className="flex gap-2.5">
      {icon}
      <span>{children}</span>
    </li>
  );
}

/**
 * The deterministic citation check, stated plainly: what the model proposed, which quotations were found in the
 * retrieved evidence, which were rejected, and which sources were confirmed in the legal database.
 */
export function VerificationNote({ result }: { result: ResearchResult }) {
  const cited = result.citations.length;
  const verified = result.citations.filter((citation) => citation.verified).length;
  const check = result.citation_check;
  const rejected = check?.rejected ?? result.unmatched_citations;

  return (
    <section aria-label="Citation verification" className="text-[13.5px] leading-relaxed text-ink-2">
      <h2 className="flex items-center gap-2">
        <ShieldCheck aria-hidden size={16} strokeWidth={1.75} className="text-verify" />
        <span className="eyebrow">Citation verification</span>
      </h2>
      <p className="mt-1.5 text-[12.5px] text-ink-3">
        Deterministic, not model-judged: each quotation the model offers must appear in the retrieved evidence, and each
        source must exist in the legal database. Citations that fail are rejected, not repaired.
      </p>

      <ul className="mt-3 space-y-1.5">
        {check && check.proposed === 0 ? (
          <Row tone="neutral">The model proposed no citations for this answer.</Row>
        ) : (
          check && (
            <Row tone={check.matched > 0 ? "ok" : "bad"}>
              {check.matched} of {check.proposed} proposed {check.proposed === 1 ? "quotation" : "quotations"} matched the
              retrieved evidence
            </Row>
          )
        )}
        {rejected > 0 && (
          <Row tone="bad">
            {rejected} {rejected === 1 ? "quotation was" : "quotations were"} rejected — the quoted text is not in the retrieved
            evidence, so {rejected === 1 ? "that citation was" : "those citations were"} dropped
          </Row>
        )}
        {cited > 0 ? (
          <Row tone={verified === cited ? "ok" : "warn"}>
            {verified === cited
              ? `${cited === 1 ? "The cited source was" : `All ${cited} cited sources were`} verified against the legal database`
              : `${verified} of ${cited} cited sources verified against the legal database`}
          </Row>
        ) : (
          <Row tone="neutral">No verified citations accompany this answer.</Row>
        )}
        {result.unverified.length > 0 && <Row tone="bad">{result.unverified.length} unverified source ids were flagged</Row>}
      </ul>

      {check && check.rejected_quotes.length > 0 && (
        <details className="group mt-3">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[12.5px] text-ink-3 hover:text-ink [&::-webkit-details-marker]:hidden">
            <ChevronRight aria-hidden size={13} className="transition-transform group-open:rotate-90" />
            Show rejected quotations
          </summary>
          <ul className="mt-2 space-y-2">
            {check.rejected_quotes.map((item, index) => (
              <li key={index} className="rounded-md border border-accent/25 bg-accent-wash/40 px-3 py-2">
                <p className="font-mono text-[10.5px] text-ink-3">claimed source: {item.doc_id ?? "none"} · not found in evidence</p>
                <p className="mt-1 text-[13px] text-ink-2 line-through decoration-accent/50">“{item.quote}”</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
