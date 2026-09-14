import { Search, SquarePen, X } from "lucide-react";
import { useState } from "react";
import { Link, useMatch } from "react-router-dom";
import { groupByDay, history, useResearchHistory, type ResearchEntry } from "../../lib/history";
import { relativeTime } from "../../lib/format";

export function HistoryPanel({ onNavigate }: { onNavigate?: () => void }) {
  const entries = useResearchHistory();
  const [filter, setFilter] = useState("");
  const activeId = useMatch("/research/:id")?.params.id;

  const needle = filter.trim().toLowerCase();
  const filtered = needle ? entries.filter((entry) => entry.question.toLowerCase().includes(needle)) : entries;
  const groups = groupByDay(filtered);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-4 pt-5 pb-3">
        <div className="flex items-center justify-between">
          <h2 className="eyebrow">Research history</h2>
          <Link
            to="/"
            onClick={onNavigate}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-ink-2 transition-colors hover:bg-sunk hover:text-ink"
          >
            <SquarePen aria-hidden size={13} strokeWidth={1.75} />
            New
          </Link>
        </div>
        {entries.length > 0 && (
          <label className="mt-3 flex h-9 items-center gap-2 rounded-md border border-rule bg-raised px-2.5 transition-colors focus-within:border-rule-strong">
            <Search aria-hidden size={14} className="text-ink-4" />
            <span className="sr-only">Search research history</span>
            <input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Search past research"
              className="min-w-0 flex-1 bg-transparent text-[13.5px] text-ink outline-none placeholder:text-ink-4"
            />
          </label>
        )}
      </div>

      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-2 pb-8">
        {entries.length === 0 ? (
          <p className="px-2 pt-1 text-[13.5px] leading-relaxed text-ink-3">
            Questions you research are kept here on this device, so you can return to an analysis and its sources.
          </p>
        ) : groups.length === 0 ? (
          <p className="px-2 pt-1 text-[13.5px] text-ink-3">No research matches “{filter.trim()}”.</p>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="mt-2 first:mt-0">
              <h3 className="px-2 pt-2 pb-1 text-[11.5px] font-medium text-ink-4">{group.label}</h3>
              <ul>
                {group.entries.map((entry) => (
                  <HistoryItem key={entry.id} entry={entry} active={entry.id === activeId} onNavigate={onNavigate} />
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}

function HistoryItem({ entry, active, onNavigate }: { entry: ResearchEntry; active: boolean; onNavigate?: () => void }) {
  const sources = entry.result.citations.length;
  return (
    <li className="group relative">
      <Link
        to={`/research/${entry.id}`}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className={`block rounded-md px-2 py-2 pr-8 transition-colors duration-150 ${active ? "bg-sunk" : "hover:bg-sunk/70"}`}
      >
        <span className="line-clamp-2 text-[13.5px] leading-snug text-ink">{entry.question}</span>
        <span className="mt-1 block text-[11.5px] text-ink-3">
          {entry.mode === "quick" ? "Quick answer" : "Research"}
          {sources > 0 && ` · ${sources} ${sources === 1 ? "source" : "sources"}`} · {relativeTime(entry.createdAt)}
        </span>
      </Link>
      <button
        type="button"
        onClick={() => history.remove(entry.id)}
        aria-label={`Remove “${entry.question}” from history`}
        className="absolute top-2 right-1.5 inline-flex size-6 items-center justify-center rounded text-ink-4 opacity-0 transition-opacity hover:bg-rule hover:text-ink group-hover:opacity-100 focus-visible:opacity-100"
      >
        <X aria-hidden size={13} />
      </button>
    </li>
  );
}
