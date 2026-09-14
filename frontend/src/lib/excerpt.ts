export interface Span {
  start: number;
  end: number;
}

export interface Segment {
  text: string;
  marked: boolean;
}

const WORD = /[\p{L}\p{N}_]+/gu;

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Finds `quote` in `text` ignoring punctuation and whitespace differences — the same
 * tolerance the backend citation mapper and document highlighter use.
 */
export function findQuote(text: string, quote: string): Span | null {
  const tokens = quote.match(WORD) ?? [];
  if (tokens.length < 3) return null;
  const pattern = new RegExp(tokens.map(escapeRegExp).join("[^\\p{L}\\p{N}_]+"), "iu");
  const match = pattern.exec(text);
  return match ? { start: match.index, end: match.index + match[0].length } : null;
}

function mergeSpans(spans: Span[]): Span[] {
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const merged: Span[] = [];
  for (const span of sorted) {
    const last = merged[merged.length - 1];
    if (last && span.start <= last.end) last.end = Math.max(last.end, span.end);
    else merged.push({ ...span });
  }
  return merged;
}

export function segmentText(text: string, spans: Span[]): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  for (const span of mergeSpans(spans)) {
    if (span.start > cursor) segments.push({ text: text.slice(cursor, span.start), marked: false });
    segments.push({ text: text.slice(span.start, span.end), marked: true });
    cursor = span.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), marked: false });
  return segments;
}

export interface Excerpt {
  segments: Segment[];
  clippedStart: boolean;
  clippedEnd: boolean;
}

/** A readable window of `text` centred on the first quoted span (or its opening, if none match). */
export function excerptAround(text: string, quotes: string[], radius = 240): Excerpt {
  const spans = quotes.map((quote) => findQuote(text, quote)).filter((span): span is Span => span !== null);
  const anchor = mergeSpans(spans)[0];

  let from = anchor ? Math.max(0, anchor.start - radius) : 0;
  let to = anchor ? Math.min(text.length, anchor.end + radius) : Math.min(text.length, radius * 2);
  if (from > 0) from = text.indexOf(" ", from) + 1 || from;
  if (to < text.length) to = text.lastIndexOf(" ", to) > from ? text.lastIndexOf(" ", to) : to;

  const windowSpans = spans
    .map((span) => ({ start: Math.max(span.start, from) - from, end: Math.min(span.end, to) - from }))
    .filter((span) => span.end > span.start);

  return {
    segments: segmentText(text.slice(from, to), windowSpans),
    clippedStart: from > 0,
    clippedEnd: to < text.length,
  };
}
