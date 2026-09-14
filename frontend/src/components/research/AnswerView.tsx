import { memo, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "../../types";
import { CitationMarker } from "./CitationMarker";

const CITATION_HREF = /^#cite-(\d+)$/;

interface AnswerViewProps {
  markdown: string;
  citations: Citation[];
  activeNumber: number | null;
  onSelectCitation: (number: number) => void;
}

/** Renders the analysis Markdown, turning each verified [n] marker into an interactive citation. */
export const AnswerView = memo(function AnswerView({ markdown, citations, activeNumber, onSelectCitation }: AnswerViewProps) {
  const byNumber = useMemo(() => new Map(citations.map((citation) => [citation.number, citation])), [citations]);

  // [n] markers become links to a sentinel href that the `a` renderer below swaps for a CitationMarker.
  const prepared = useMemo(() => markdown.replace(/\[(\d{1,3})\](?!\()/g, "[$1](#cite-$1)"), [markdown]);

  const components = useMemo<Components>(
    () => ({
      a: ({ node: _node, href, children, ...rest }) => {
        const match = href?.match(CITATION_HREF);
        if (match) {
          const number = Number(match[1]);
          return (
            <CitationMarker
              number={number}
              citation={byNumber.get(number)}
              active={activeNumber === number}
              onSelect={onSelectCitation}
            />
          );
        }
        return (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="underline decoration-rule-strong underline-offset-4 hover:decoration-accent"
            {...rest}
          >
            {children}
          </a>
        );
      },
    }),
    [byNumber, activeNumber, onSelectCitation],
  );

  return (
    <div className="brief">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {prepared}
      </ReactMarkdown>
    </div>
  );
});
