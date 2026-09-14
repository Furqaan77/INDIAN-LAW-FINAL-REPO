import type { DocumentSummary, SourceType } from "../types";

export const SOURCE_LABEL: Record<SourceType, string> = {
  statute: "Statute",
  case_law: "Case law",
  pdf: "Other source",
};

export function sourceKind(type: string | null | undefined): SourceType {
  return type === "statute" || type === "case_law" ? type : "pdf";
}

export function formatDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-IN").format(value);
}

/** Scraped judgment titles read like "A vs . B on 20 October, 2020"; present them as "A v. B". */
export function cleanCaseTitle(title: string): string {
  return title
    .replace(/\s+on\s+\d{1,2}\s+[A-Za-z]+,?\s+\d{4}\s*$/, "")
    .replace(/\s+vs?\s*\.?\s*$/i, "") // a dangling "vs ." where the scraped title omits the other party
    .replace(/\s+vs?\s*\.?\s+/gi, " v. ")
    .replace(/\.{2,}\s*/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

const ACT_ABBREVIATIONS: Record<string, string> = {
  ipc: "IPC",
  bns: "BNS",
  crpc: "CrPC",
  bnss: "BNSS",
  iea: "IEA",
  bsa: "BSA",
  "ni-act": "NI Act",
  "income-tax-act": "IT Act, 1961",
  "income-tax-act-2025": "IT Act, 2025",
};

export function actShortName(actId: string | null | undefined, fallback?: string | null): string {
  if (actId && ACT_ABBREVIATIONS[actId]) return ACT_ABBREVIATIONS[actId];
  return (fallback ?? actId ?? "").replace(/^The\s+/, "");
}

export interface SourceHeading {
  /** What the source is: a section heading or a case name. */
  primary: string;
  /** Where it sits: the Act, or the court and date. */
  secondary: string | null;
  /** Compact locator shown in mono, e.g. "§ 138". */
  locator: string | null;
}

export function describeSource(document: DocumentSummary | null | undefined, fallbackTitle: string): SourceHeading {
  const statute = document?.statute;
  if (statute) {
    const section = statute.section_number;
    return {
      primary: statute.section_heading || (section ? `Section ${section}` : fallbackTitle),
      secondary: statute.act_title ?? null,
      locator: section ? `§ ${section}` : null,
    };
  }
  if (document?.source_type === "case_law") {
    return {
      primary: cleanCaseTitle(document.title),
      secondary: [document.court, formatDate(document.date)].filter(Boolean).join(" · ") || null,
      locator: null,
    };
  }
  return { primary: fallbackTitle, secondary: document?.file_name ?? null, locator: null };
}

export const RELATION_LABEL: Record<string, string> = {
  official: "Officially mapped",
  "near-identical": "Near-identical",
  close: "Close match",
  weak: "Partial overlap",
  none: "No equivalent",
  "official-none": "No equivalent (official)",
};

export function relativeTime(timestamp: number): string {
  const seconds = Math.round((Date.now() - timestamp) / 1000);
  if (seconds < 60) return "Just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const date = new Date(timestamp);
  const sameDay = new Date().toDateString() === date.toDateString();
  return sameDay
    ? date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
