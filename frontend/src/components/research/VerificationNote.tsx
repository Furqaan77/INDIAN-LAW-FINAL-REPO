import { CircleAlert, ShieldCheck } from "lucide-react";
import type { ResearchResult } from "../../types";

/** A quiet account of what was verified — stated once, below the analysis, not as badges everywhere. */
export function VerificationNote({ result }: { result: ResearchResult }) {
  const cited = result.citations.length;
  const verified = result.citations.filter((citation) => citation.verified).length;
  const unmatched = result.unmatched_citations;

  if (cited === 0) {
    return (
      <p className="flex gap-2.5 text-[13.5px] leading-relaxed text-ink-3">
        <CircleAlert aria-hidden size={16} strokeWidth={1.75} className="mt-0.5 shrink-0 text-ink-4" />
        <span>
          No citations accompany this answer — the retrieved sources did not contain passages that directly support a cited
          conclusion.
        </span>
      </p>
    );
  }

  const allVerified = verified === cited;
  return (
    <div className="flex gap-2.5 text-[13.5px] leading-relaxed text-ink-3">
      {allVerified ? (
        <ShieldCheck aria-hidden size={16} strokeWidth={1.75} className="mt-0.5 shrink-0 text-verify" />
      ) : (
        <CircleAlert aria-hidden size={16} strokeWidth={1.75} className="mt-0.5 shrink-0 text-caution" />
      )}
      <p>
        <span className={allVerified ? "text-ink-2" : "text-caution"}>
          {allVerified
            ? `${cited === 1 ? "The cited source was" : `All ${cited} cited sources were`} verified`
            : `${verified} of ${cited} cited sources verified`}
        </span>{" "}
        — each quotation was matched to a retrieved passage and the source checked against the legal database.
        {unmatched > 0 &&
          ` ${unmatched === 1 ? "One quotation" : `${unmatched} quotations`} could not be matched to a retrieved passage, so ${
            unmatched === 1 ? "its citation was" : "those citations were"
          } removed.`}
      </p>
    </div>
  );
}
