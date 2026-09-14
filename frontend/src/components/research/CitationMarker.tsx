import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { decodeEntities } from "../../lib/entities";
import { describeSource } from "../../lib/format";
import type { Citation } from "../../types";
import { SourceTypeLabel, VerifiedMark } from "../primitives";

const PREVIEW_WIDTH = 320;
const PREVIEW_DELAY_MS = 140;

interface CitationMarkerProps {
  number: number;
  citation: Citation | undefined;
  active: boolean;
  onSelect: (number: number) => void;
}

/** Inline citation — hover or focus previews the source, click opens its evidence. */
export function CitationMarker({ number, citation, active, onSelect }: CitationMarkerProps) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [anchor, setAnchor] = useState<DOMRect | null>(null);

  const show = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (buttonRef.current) setAnchor(buttonRef.current.getBoundingClientRect());
    }, PREVIEW_DELAY_MS);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setAnchor(null);
  };

  useEffect(() => () => window.clearTimeout(timer.current), []);

  useEffect(() => {
    if (!anchor) return;
    const dismiss = () => setAnchor(null);
    window.addEventListener("scroll", dismiss, true);
    window.addEventListener("resize", dismiss);
    return () => {
      window.removeEventListener("scroll", dismiss, true);
      window.removeEventListener("resize", dismiss);
    };
  }, [anchor]);

  if (!citation) {
    return <sup className="font-sans text-[10.5px] text-ink-4">[{number}]</sup>;
  }

  const heading = describeSource(citation.document, citation.title);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={() => {
          hide();
          onSelect(number);
        }}
        aria-label={`Source ${number}: ${heading.primary}${heading.secondary ? `, ${heading.secondary}` : ""}`}
        aria-pressed={active}
        className={`relative -top-[0.42em] mx-[1.5px] inline-flex h-[1.1rem] min-w-[1.1rem] items-center justify-center rounded-[4px] px-[3px] align-baseline font-sans text-[10.5px] leading-none font-semibold tabular-nums transition-colors duration-150 ${
          active ? "bg-accent text-paper" : "bg-accent-wash text-accent hover:bg-accent hover:text-paper"
        }`}
      >
        {number}
      </button>
      {createPortal(
        <AnimatePresence>
          {anchor && <CitationPreview anchor={anchor} citation={citation} heading={heading} />}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}

function CitationPreview({
  anchor,
  citation,
  heading,
}: {
  anchor: DOMRect;
  citation: Citation;
  heading: ReturnType<typeof describeSource>;
}) {
  const left = Math.min(
    Math.max(anchor.left + anchor.width / 2 - PREVIEW_WIDTH / 2, 12),
    window.innerWidth - PREVIEW_WIDTH - 12,
  );
  const above = anchor.top > 240;
  const position = above ? { bottom: window.innerHeight - anchor.top + 8 } : { top: anchor.bottom + 8 };
  const quote = citation.quotes[0] ? decodeEntities(citation.quotes[0]) : null;

  return (
    <motion.div
      role="tooltip"
      initial={{ opacity: 0, y: above ? 4 : -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
      style={{ left, width: PREVIEW_WIDTH, ...position }}
      className="pointer-events-none fixed z-[60] rounded-lg border border-rule bg-raised p-4 shadow-float"
    >
      <div className="flex items-center justify-between gap-3">
        <SourceTypeLabel type={citation.source_type} />
        <VerifiedMark verified={citation.verified} compact />
      </div>
      <p className="mt-2 font-serif text-[15.5px] leading-snug text-ink">{heading.primary}</p>
      {(heading.secondary || heading.locator) && (
        <p className="mt-1 text-[12px] leading-snug text-ink-3">
          {[heading.secondary, heading.locator].filter(Boolean).join(" · ")}
        </p>
      )}
      {quote && (
        <p className="mt-3 line-clamp-4 border-l-2 border-mark pl-3 font-serif text-[13.5px] leading-relaxed text-ink-2 italic">
          “{quote}”
        </p>
      )}
      <p className="mt-3 text-[11.5px] text-ink-4">Click to open the evidence</p>
    </motion.div>
  );
}
