const NAMED: Record<string, string> = { amp: "&", quot: '"', apos: "'", lt: "<", gt: ">", nbsp: " " };

/**
 * Scraped judgment text stores HTML entities literally (&quot;, &amp;, &#x27;). The API decodes
 * them now, but research saved to history earlier still carries them, so decode again for display.
 * Idempotent on already-clean text.
 */
export function decodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (match, code: string) => {
    if (code.startsWith("#")) {
      const value = code[1]?.toLowerCase() === "x" ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
      return Number.isFinite(value) && value > 0 && value <= 0x10ffff ? String.fromCodePoint(value) : match;
    }
    return NAMED[code.toLowerCase()] ?? match;
  });
}
