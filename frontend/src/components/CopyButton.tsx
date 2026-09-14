import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

async function writeClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.appendChild(field);
  field.select();
  document.execCommand("copy");
  field.remove();
}

interface CopyButtonProps {
  text: string | (() => string);
  label: string;
  showLabel?: boolean;
  className?: string;
}

export function CopyButton({ text, label, showLabel = false, className = "" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    try {
      await writeClipboard(typeof text === "function" ? text() : text);
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  const Icon = copied ? Check : Copy;
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={showLabel ? undefined : label}
      title={label}
      className={`inline-flex items-center gap-1.5 rounded-md text-[12.5px] transition-colors duration-150 ${
        copied ? "text-verify" : "text-ink-3 hover:text-ink"
      } ${showLabel ? "h-8 px-2 hover:bg-sunk" : "size-8 justify-center hover:bg-sunk"} ${className}`}
    >
      <Icon aria-hidden size={14} strokeWidth={1.75} />
      {showLabel && <span>{copied ? "Copied" : label}</span>}
      <span aria-live="polite" className="sr-only">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </button>
  );
}
