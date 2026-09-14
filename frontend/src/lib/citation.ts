import type { DocumentSummary } from "../types";
import { cleanCaseTitle, formatDate } from "./format";

/** A conventional, human-readable reference suitable for pasting into notes or a brief. */
export function formatCitation(title: string, document: DocumentSummary | null | undefined): string {
  const statute = document?.statute;
  if (statute) {
    const reference = [statute.section_number ? `Section ${statute.section_number}` : null, statute.act_title]
      .filter(Boolean)
      .join(", ");
    return statute.section_heading ? `${reference} — ${statute.section_heading}` : reference || title;
  }
  if (document?.source_type === "case_law") {
    const detail = [document.court, formatDate(document.date)].filter(Boolean).join(", ");
    return detail ? `${cleanCaseTitle(document.title)} (${detail})` : cleanCaseTitle(document.title);
  }
  return title;
}

export function sourceHref(docId: string): string {
  return `/source/${encodeURIComponent(docId)}`;
}

/** Router state handed to the document reader so it can highlight the passages the analysis relied on. */
export interface SourceLinkState {
  quotes: string[];
  citationNumber?: number;
  returnTo?: string;
  returnLabel?: string;
  /** How the reader describes the highlighted passages, e.g. for search matches rather than citations. */
  highlightLabel?: string;
}
