import { ArrowRight } from "lucide-react";
import type { KeyboardEvent } from "react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHotkey } from "../../hooks/useHotkey";
import { loadEngineSelection, saveEngineSelection } from "../../lib/engines";
import { MODES, destinationFor, type ModeId } from "../../lib/modes";
import type { EngineKey } from "../../types";
import { Kbd } from "../primitives";
import { EngineToggleGroup } from "./EngineControls";

interface CommandBarProps {
  initialQuery?: string;
  initialMode?: ModeId;
  variant?: "hero" | "compact";
  autoFocus?: boolean;
  /** Restrict which modes are offered (e.g. only research modes inside the workspace). */
  modes?: ModeId[];
  /** Answer engines preselected for the next question (default: the last selection in this browser). */
  initialEngines?: EngineKey[];
}

/** The research entry point: a query field with a mode selector, not a chat box. */
export function CommandBar({
  initialQuery = "",
  initialMode = "research",
  variant = "hero",
  autoFocus = false,
  modes,
  initialEngines,
}: CommandBarProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState(initialQuery);
  const [mode, setMode] = useState<ModeId>(initialMode);
  const [engines, setEngines] = useState<EngineKey[]>(() => initialEngines ?? loadEngineSelection());
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const radioRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const fieldId = useId();
  const hero = variant === "hero";

  const available = modes ? MODES.filter((m) => modes.includes(m.id)) : MODES;
  const active = available.find((m) => m.id === mode) ?? available[0];

  useEffect(() => setQuery(initialQuery), [initialQuery]);
  useEffect(() => setMode(initialMode), [initialMode]);

  useLayoutEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(element.scrollHeight, hero ? 232 : 168)}px`;
  }, [query, hero]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus({ preventScroll: true });
  }, [autoFocus]);

  useHotkey("/", () => textareaRef.current?.focus());

  const trimmed = query.trim();
  const canSubmit = trimmed.length >= (active.id === "compare" ? 3 : 3);

  function submit() {
    if (!canSubmit) return;
    const answers = active.id === "research" || active.id === "quick";
    const destination = destinationFor(active.id, trimmed, answers ? engines : undefined);
    if (!destination.ok) {
      setError(destination.message);
      return;
    }
    if (answers) saveEngineSelection(engines);
    setError(null);
    navigate(destination.to);
  }

  function onFieldKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  function selectMode(id: ModeId, focusField = true) {
    setMode(id);
    setError(null);
    if (focusField) textareaRef.current?.focus();
  }

  function onModeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = available.findIndex((m) => m.id === active.id);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? available.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + available.length) % available.length;
    selectMode(available[next].id, false);
    radioRefs.current[available[next].id]?.focus();
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="w-full"
    >
      <div
        className={`relative border border-rule-strong bg-raised shadow-lift transition-[border-color,box-shadow] duration-200 focus-within:border-ink-3 focus-within:shadow-[0_0_0_4px_var(--accent-wash),0_10px_28px_-12px_rgb(var(--shadow)/0.18)] ${
          hero ? "rounded-[20px]" : "rounded-2xl"
        }`}
      >
        {available.length > 1 && (
          <div
            role="radiogroup"
            aria-label="Research mode"
            className="flex gap-1 overflow-x-auto px-3 pt-3 [scrollbar-width:none] max-sm:pr-10 max-sm:[mask-image:linear-gradient(to_right,black_80%,transparent)] [&::-webkit-scrollbar]:hidden"
          >
            {available.map((m) => {
              const checked = m.id === active.id;
              return (
                <button
                  key={m.id}
                  ref={(element) => {
                    radioRefs.current[m.id] = element;
                  }}
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  tabIndex={checked ? 0 : -1}
                  onClick={() => selectMode(m.id)}
                  onKeyDown={onModeKeyDown}
                  className={`h-7 shrink-0 rounded-full px-3 text-[12.5px] transition-colors duration-150 ${
                    checked ? "bg-ink text-paper" : "text-ink-3 hover:bg-sunk hover:text-ink"
                  }`}
                >
                  {m.label}
                </button>
              );
            })}
          </div>
        )}

        <label htmlFor={fieldId} className="sr-only">
          {active.label}
        </label>
        <textarea
          id={fieldId}
          ref={textareaRef}
          value={query}
          rows={1}
          onChange={(event) => {
            setQuery(event.target.value);
            if (error) setError(null);
          }}
          onKeyDown={onFieldKeyDown}
          placeholder={active.placeholder}
          enterKeyHint="search"
          spellCheck
          aria-invalid={!!error}
          aria-describedby={`${fieldId}-hint${error ? ` ${fieldId}-error` : ""}`}
          className={`block w-full resize-none bg-transparent px-5 font-serif text-ink outline-none placeholder:text-ink-4 placeholder:italic ${
            hero ? "pt-4 pb-2 text-[1.375rem] leading-[1.45] sm:text-[1.5rem]" : "pt-3 pb-1 text-[1.125rem] leading-snug"
          }`}
        />

        {(active.id === "research" || active.id === "quick") && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-2">
            <span className="text-[12px] font-medium text-ink-3">Answer with</span>
            <EngineToggleGroup selected={engines} onChange={setEngines} size="sm" />
          </div>
        )}

        <div className="flex items-center gap-3 py-3 pr-3 pl-5">
          <p id={`${fieldId}-hint`} className="min-w-0 flex-1 truncate text-[12.5px] text-ink-3">
            {active.hint}
          </p>
          <span className="hidden items-center gap-1.5 text-[11.5px] text-ink-4 sm:inline-flex" aria-hidden>
            <Kbd>↵</Kbd>
          </span>
          <button
            type="submit"
            disabled={!canSubmit}
            className="group/submit inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-accent pr-3 pl-4 text-[13.5px] font-medium text-paper transition-[background-color,opacity] duration-150 hover:bg-accent-ink disabled:opacity-35"
          >
            {active.verb}
            <ArrowRight aria-hidden size={15} className="transition-transform duration-200 group-hover/submit:translate-x-0.5" />
          </button>
        </div>
      </div>
      {error && (
        <p id={`${fieldId}-error`} role="alert" className="mt-2.5 px-2 text-[13.5px] text-caution">
          {error}
        </p>
      )}
    </form>
  );
}
