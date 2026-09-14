import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import { sourceHref, type SourceLinkState } from "../../lib/citation";
import { describeSource } from "../../lib/format";
import type { ResearchResult, RetrievedDocument } from "../../types";
import { SkeletonLines, SourceGlyph } from "../primitives";
import { SourceSlip } from "./SourceSlip";

interface EvidenceRailProps {
  result: ResearchResult;
  activeNumber: number | null;
  onSelect: (number: number) => void;
  headerAction?: ReactNode;
}

export function EvidenceRail({ result, activeNumber, onSelect, headerAction }: EvidenceRailProps) {
  const slipRefs = useRef(new Map<number, HTMLLIElement>());
  const { citations } = result;

  useEffect(() => {
    if (activeNumber === null) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    slipRefs.current.get(activeNumber)?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" });
  }, [activeNumber]);

  const uncited = useMemo(() => {
    const seen = new Set<string>();
    return result.retrieved_documents.filter((document) => {
      if (document.cited || seen.has(document.doc_id)) return false;
      seen.add(document.doc_id);
      return true;
    });
  }, [result.retrieved_documents]);

  const statutes = citations.filter((citation) => citation.source_type === "statute").length;
  const judgments = citations.filter((citation) => citation.source_type === "case_law").length;
  const breakdown = [statutes ? `${statutes} statutory` : null, judgments ? `${judgments} judicial` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <RailHeader action={headerAction}>
        {citations.length} {citations.length === 1 ? "source" : "sources"}
        {breakdown && ` · ${breakdown}`}
      </RailHeader>

      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
        {citations.length === 0 ? (
          <p className="text-[13.5px] leading-relaxed text-ink-3">
            This answer cites no sources. The documents retrieved for the question are listed below so you can read them
            directly.
          </p>
        ) : (
          <ol className="space-y-3">
            {citations.map((citation) => (
              <li
                key={citation.doc_id}
                ref={(element) => {
                  if (element) slipRefs.current.set(citation.number, element);
                  else slipRefs.current.delete(citation.number);
                }}
                className="scroll-mt-4"
              >
                <SourceSlip
                  citation={citation}
                  active={activeNumber === citation.number}
                  onActivate={() => onSelect(citation.number)}
                />
              </li>
            ))}
          </ol>
        )}
        {uncited.length > 0 && <RetrievedList documents={uncited} defaultOpen={citations.length === 0} />}
      </div>
    </div>
  );
}

function RailHeader({ children, action }: { children?: ReactNode; action?: ReactNode }) {
  return (
    <header className="flex min-h-[52px] items-center gap-3 border-b border-rule px-5 py-2">
      <h2 className="eyebrow">Evidence</h2>
      {children && <span className="text-[12px] text-ink-3">{children}</span>}
      {action && <span className="ml-auto">{action}</span>}
    </header>
  );
}

function RetrievedList({ documents, defaultOpen }: { documents: RetrievedDocument[]; defaultOpen: boolean }) {
  const location = useLocation();
  const state: SourceLinkState = {
    quotes: [],
    returnTo: `${location.pathname}${location.search}`,
    returnLabel: "Back to analysis",
  };

  return (
    <details open={defaultOpen} className="group mt-6 border-t border-rule pt-4">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md py-1 text-[12.5px] text-ink-3 transition-colors hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight aria-hidden size={13} className="transition-transform duration-200 group-open:rotate-90" />
        Also retrieved, not cited
        <span className="text-ink-4 tabular-nums">{documents.length}</span>
      </summary>
      <ul className="mt-2 space-y-0.5">
        {documents.map((document) => {
          const heading = describeSource(document.document, document.title);
          return (
            <li key={document.doc_id}>
              <Link
                to={sourceHref(document.doc_id)}
                state={state}
                className="flex gap-2.5 rounded-md px-2 py-2 transition-colors hover:bg-sunk"
              >
                <span className="mt-[3px] w-3 shrink-0 text-center">
                  <SourceGlyph type={document.source_type} />
                </span>
                <span className="min-w-0">
                  <span className="line-clamp-2 block text-[13.5px] leading-snug text-ink">{heading.primary}</span>
                  {heading.secondary && <span className="mt-0.5 block truncate text-[12px] text-ink-3">{heading.secondary}</span>}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

/** Holds the rail's shape while research runs, so the layout doesn't jump when evidence arrives. */
export function EvidenceRailPlaceholder() {
  return (
    <div className="flex h-full flex-col" aria-hidden>
      <RailHeader>Gathering sources</RailHeader>
      <div className="space-y-3 px-5 py-4">
        {[0, 1, 2].map((key) => (
          <div key={key} className="rounded-lg border border-rule bg-raised p-4" style={{ opacity: 1 - key * 0.25 }}>
            <div className="skeleton h-3 w-24" />
            <div className="skeleton mt-3 h-4 w-4/5" />
            <SkeletonLines lines={3} className="mt-4" />
          </div>
        ))}
      </div>
    </div>
  );
}
