import { ArrowUpRight, ChevronDown } from "lucide-react";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { formatCitation, sourceHref, type SourceLinkState } from "../../lib/citation";
import { decodeEntities } from "../../lib/entities";
import { excerptAround } from "../../lib/excerpt";
import { describeSource } from "../../lib/format";
import type { Citation } from "../../types";
import { CopyButton } from "../CopyButton";
import { SourceTypeLabel, VerifiedMark } from "../primitives";

interface SourceSlipProps {
  citation: Citation;
  active: boolean;
  onActivate: () => void;
}

/** One cited authority: what it is, where it sits, and the exact passage the analysis relied on. */
export function SourceSlip({ citation, active, onActivate }: SourceSlipProps) {
  const location = useLocation();
  const [expanded, setExpanded] = useState(false);
  const heading = describeSource(citation.document, citation.title);
  const passage = decodeEntities(citation.passages[0] ?? citation.excerpt);
  const quotes = citation.quotes.map(decodeEntities);
  const excerpt = excerptAround(passage, quotes, expanded ? passage.length : 240);
  const titleId = `source-${citation.number}-title`;

  const linkState: SourceLinkState = {
    quotes,
    citationNumber: citation.number,
    returnTo: `${location.pathname}${location.search}`,
    returnLabel: "Back to analysis",
  };

  return (
    <article
      aria-labelledby={titleId}
      className={`rounded-lg border bg-raised transition-[border-color,box-shadow] duration-200 ${
        active ? "border-accent/55 shadow-lift" : "border-rule hover:border-rule-strong"
      }`}
    >
      <div className="relative px-4 pt-3.5 pb-3">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className={`inline-flex h-5 min-w-5 items-center justify-center rounded-[4px] px-1 text-[11px] font-semibold tabular-nums transition-colors ${
              active ? "bg-accent text-paper" : "bg-accent-wash text-accent"
            }`}
          >
            {citation.number}
          </span>
          <SourceTypeLabel type={citation.source_type} />
          <span className="relative z-10 ml-auto">
            <VerifiedMark verified={citation.verified} compact />
          </span>
        </div>
        <h3 id={titleId} className="mt-2.5 font-serif text-[16.5px] leading-snug text-ink">
          <button
            type="button"
            onClick={onActivate}
            aria-pressed={active}
            className="text-left outline-none after:absolute after:inset-0 after:rounded-t-lg focus-visible:after:outline-2 focus-visible:after:outline-accent"
          >
            <span className="sr-only">Source {citation.number}: </span>
            {heading.primary}
          </button>
        </h3>
        {(heading.secondary || heading.locator) && (
          <p className="mt-1 text-[12.5px] leading-snug text-ink-3">
            {[heading.secondary, heading.locator].filter(Boolean).join(" · ")}
          </p>
        )}
        <p className="mt-1 font-mono text-[10.5px] break-all text-ink-4">
          {[
            citation.doc_id,
            citation.page_start ? (citation.page_end && citation.page_end !== citation.page_start ? `pp. ${citation.page_start}–${citation.page_end}` : `p. ${citation.page_start}`) : null,
            citation.verified ? "verified in database" : "not verified",
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>

      <div className="border-t border-rule px-4 py-3">
        <p className="eyebrow mb-1.5">Source text</p>
        <blockquote className="legal-text text-[14.5px] leading-[1.68] text-ink-2">
          {excerpt.clippedStart && <span className="text-ink-4">… </span>}
          {excerpt.segments.map((segment, index) =>
            segment.marked ? (
              <mark key={index} className="evidence text-ink">
                {segment.text}
              </mark>
            ) : (
              <span key={index}>{segment.text}</span>
            ),
          )}
          {excerpt.clippedEnd && <span className="text-ink-4"> …</span>}
        </blockquote>
      </div>

      <footer className="flex items-center gap-0.5 border-t border-rule px-2 py-1.5">
        <Link
          to={sourceHref(citation.doc_id)}
          state={linkState}
          className="group inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-medium text-ink transition-colors hover:bg-sunk"
        >
          Open source
          <ArrowUpRight aria-hidden size={13} className="transition-transform group-hover:-translate-y-px group-hover:translate-x-px" />
        </Link>
        {(excerpt.clippedStart || excerpt.clippedEnd || expanded) && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-[12.5px] text-ink-3 transition-colors hover:bg-sunk hover:text-ink"
          >
            {expanded ? "Shorter" : "Full passage"}
            <ChevronDown aria-hidden size={13} className={`transition-transform duration-200 ${expanded ? "rotate-180" : ""}`} />
          </button>
        )}
        <CopyButton className="ml-auto" text={formatCitation(citation.title, citation.document)} label="Copy citation" />
      </footer>
    </article>
  );
}
