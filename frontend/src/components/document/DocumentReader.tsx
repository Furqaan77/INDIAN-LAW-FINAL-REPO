import { ArrowRight, ChevronDown, ChevronUp, Search } from "lucide-react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAsync } from "../../hooks/useAsync";
import { useHotkey } from "../../hooks/useHotkey";
import { api } from "../../lib/api";
import { sourceHref } from "../../lib/citation";
import type { Span } from "../../lib/excerpt";
import { RELATION_LABEL, actShortName } from "../../lib/format";
import type { Correspondence, Highlight } from "../../types";
import { IconButton, SkeletonLines } from "../primitives";

const STATUTE_BREAK = /\s+(?=(?:\(\d+[A-Za-z]{0,2}\)|Explanation\b|Provided\s+(?:further\s+|also\s+)?that\b|Illustrations?\b))/g;
const SENTENCE_BREAK = /(?<=[.?!][”"’)]?)\s+(?=[A-Z“"(])/g;
const JUDGMENT_PARAGRAPH_CHARS = 650;

/**
 * Splits a document into reading paragraphs as offset spans over the original text, so the
 * backend's highlight offsets still line up. Statutes break before sub-sections, provisos and
 * explanations; judgments (stored as continuous text) break at sentence ends every few hundred
 * characters.
 */
export function paragraphSpans(text: string, kind: "statute" | "judgment"): Span[] {
  const starts = [0];
  if (kind === "statute") {
    for (const match of text.matchAll(STATUTE_BREAK)) {
      const previous = text[(match.index ?? 0) - 1];
      if (match.index === 0 || (previous && ".:;—–-".includes(previous))) starts.push((match.index ?? 0) + match[0].length);
    }
  } else {
    let last = 0;
    for (const match of text.matchAll(SENTENCE_BREAK)) {
      const position = (match.index ?? 0) + match[0].length;
      if (position - last >= JUDGMENT_PARAGRAPH_CHARS) {
        starts.push(position);
        last = position;
      }
    }
  }
  return starts
    .map((start, index) => ({ start, end: starts[index + 1] ?? text.length }))
    .filter((span) => text.slice(span.start, span.end).trim());
}

interface LegalTextProps {
  text: string;
  kind: "statute" | "judgment";
  highlights: Highlight[];
  activeHighlight: number;
}

export function LegalText({ text, kind, highlights, activeHighlight }: LegalTextProps) {
  const paragraphs = useMemo(() => paragraphSpans(text, kind), [text, kind]);

  return (
    <div className="legal-text space-y-[1.05em]">
      {paragraphs.map((paragraph) => {
        const nodes: ReactNode[] = [];
        let cursor = paragraph.start;
        highlights.forEach((highlight, index) => {
          const start = Math.max(highlight.start, paragraph.start, cursor);
          const end = Math.min(highlight.end, paragraph.end);
          if (end <= start) return;
          if (start > cursor) nodes.push(text.slice(cursor, start));
          nodes.push(
            <mark
              key={`${index}-${start}`}
              data-evidence={index}
              className={`evidence scroll-mt-40 transition-shadow duration-300 ${
                index === activeHighlight ? "shadow-[inset_0_-2px_0_var(--accent)]" : ""
              }`}
            >
              {text.slice(start, end)}
            </mark>,
          );
          cursor = end;
        });
        if (cursor < paragraph.end) nodes.push(text.slice(cursor, paragraph.end));
        return <p key={paragraph.start}>{nodes}</p>;
      })}
    </div>
  );
}

interface HighlightNavigatorProps {
  count: number;
  index: number;
  citationNumber?: number;
  label?: string;
  onChange: (index: number) => void;
}

export function HighlightNavigator({ count, index, citationNumber, label, onChange }: HighlightNavigatorProps) {
  const previous = () => onChange((index - 1 + count) % count);
  const next = () => onChange((index + 1) % count);
  useHotkey("n", next, { enabled: count > 1 });
  useHotkey("p", previous, { enabled: count > 1 });

  return (
    <div className="flex items-center gap-3 rounded-lg border border-rule bg-raised/95 py-1.5 pr-1.5 pl-4 shadow-lift backdrop-blur">
      <span aria-hidden className="h-3.5 w-2.5 shrink-0 rounded-[2px] bg-mark ring-1 ring-rule-strong" />
      <p className="min-w-0 flex-1 truncate text-[13px] text-ink-2" aria-live="polite">
        {label ?? (citationNumber ? `Passage relied on for citation [${citationNumber}]` : "Cited passage")}
        {count > 1 && (
          <span className="text-ink-3">
            {" "}
            · {index + 1} of {count}
          </span>
        )}
      </p>
      {count > 1 && (
        <div className="flex">
          <IconButton label="Previous cited passage (P)" size="sm" onClick={previous}>
            <ChevronUp aria-hidden size={16} />
          </IconButton>
          <IconButton label="Next cited passage (N)" size="sm" onClick={next}>
            <ChevronDown aria-hidden size={16} />
          </IconButton>
        </div>
      )}
    </div>
  );
}

export function MetadataList({ items }: { items: [string, ReactNode][] }) {
  const present = items.filter(([, value]) => value !== null && value !== undefined && value !== "");
  return (
    <dl className="divide-y divide-rule border-y border-rule">
      {present.map(([label, value]) => (
        <div key={label} className="grid grid-cols-[7.5rem_1fr] gap-3 py-2.5">
          <dt className="text-[12.5px] text-ink-3">{label}</dt>
          <dd className="min-w-0 text-[13.5px] leading-snug break-words text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

interface CorrespondenceListProps {
  correspondences: Correspondence[];
  actId: string | null;
  sectionNumber: string | null;
}

export function CorrespondenceList({ correspondences, actId, sectionNumber }: CorrespondenceListProps) {
  if (!correspondences.length) return null;
  const successor = correspondences[0].direction === "successor";

  return (
    <section aria-labelledby="correspondence-heading">
      <h2 id="correspondence-heading" className="eyebrow">
        {successor ? "Replaced in the new code by" : "Replaces, in the old code"}
      </h2>
      <ul className="mt-3 divide-y divide-rule border-y border-rule">
        {correspondences.map((item, index) => {
          const statute = item.document?.statute;
          const noEquivalent = item.relation?.includes("none");
          return (
            <li key={index} className="py-3">
              <p className="text-[12px] text-ink-3">
                {RELATION_LABEL[item.relation] ?? item.relation}
                {item.score !== null && !noEquivalent && (
                  <span className="font-mono text-ink-4"> · similarity {item.score.toFixed(2)}</span>
                )}
              </p>
              {item.document && statute ? (
                <Link
                  to={sourceHref(item.document.doc_id)}
                  className="mt-1 block font-serif text-[15.5px] leading-snug text-ink transition-colors hover:text-accent"
                >
                  <span className="font-mono text-[12.5px] text-ink-3">
                    {actShortName(statute.act_id, statute.act_title)} § {statute.section_number}
                  </span>{" "}
                  {statute.section_heading}
                </Link>
              ) : (
                <p className="mt-1 text-[14px] text-ink-3">
                  {noEquivalent
                    ? "No corresponding provision"
                    : `${actShortName(item.act_id)} § ${item.section_number} — not in the database`}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {actId && sectionNumber && correspondences.some((item) => item.document) && (
        <Link
          to={`/compare?${new URLSearchParams({ act: actId, section: sectionNumber })}`}
          className="group mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-ink"
        >
          Compare side by side
          <ArrowRight aria-hidden size={14} className="transition-transform group-hover:translate-x-0.5" />
        </Link>
      )}
    </section>
  );
}

export function ActSectionNav({ actId, currentDocId }: { actId: string; currentDocId: string }) {
  const { state } = useAsync(actId, (signal) => api.actSections(actId, signal));
  const [filter, setFilter] = useState("");

  if (state.status === "error") return null;

  const act = state.status === "success" ? state.data : null;
  const needle = filter.trim().toLowerCase();
  const sections = act
    ? act.sections.filter(
        (section) =>
          !needle ||
          `${section.section_number ?? ""} ${section.section_heading ?? ""}`.toLowerCase().includes(needle),
      )
    : [];

  return (
    <nav aria-labelledby="act-sections-heading">
      <h2 id="act-sections-heading" className="eyebrow">
        Sections of this Act {act && <span className="text-ink-4">· {act.sections.length}</span>}
      </h2>
      {act && act.sections.length > 20 && (
        <label className="mt-3 flex h-8 items-center gap-2 rounded-md border border-rule bg-raised px-2.5 focus-within:border-rule-strong">
          <Search aria-hidden size={13} className="text-ink-4" />
          <span className="sr-only">Filter sections</span>
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter by number or heading"
            className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-ink-4"
          />
        </label>
      )}
      <div className="scroll-quiet mt-2 max-h-[46vh] overflow-y-auto">
        {!act ? (
          <SkeletonLines lines={6} className="py-2" />
        ) : (
          <ul>
            {sections.map((section) => {
              const current = section.doc_id === currentDocId;
              return (
                <li key={section.doc_id}>
                  <Link
                    to={sourceHref(section.doc_id)}
                    aria-current={current ? "page" : undefined}
                    className={`flex gap-3 rounded-md px-2 py-1.5 text-[13px] transition-colors ${
                      current ? "bg-sunk text-ink" : "text-ink-2 hover:bg-sunk/70 hover:text-ink"
                    }`}
                  >
                    <span className="w-10 shrink-0 font-mono text-[12px] text-ink-3 tabular-nums">{section.section_number}</span>
                    <span className="line-clamp-2 min-w-0">{section.section_heading ?? "Untitled section"}</span>
                  </Link>
                </li>
              );
            })}
            {sections.length === 0 && <li className="px-2 py-2 text-[13px] text-ink-3">No sections match.</li>}
          </ul>
        )}
      </div>
    </nav>
  );
}
