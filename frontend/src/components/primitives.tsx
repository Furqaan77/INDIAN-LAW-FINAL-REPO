import { CircleAlert, CircleCheck, FileText, Scale } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { forwardRef } from "react";
import { SOURCE_LABEL, sourceKind } from "../lib/format";

type ButtonVariant = "primary" | "secondary" | "ghost";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow] duration-150 disabled:opacity-45 disabled:pointer-events-none";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-ink text-paper hover:bg-ink-2 shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]",
  secondary: "border border-rule-strong bg-raised text-ink hover:border-ink-3 hover:bg-paper",
  ghost: "text-ink-2 hover:bg-sunk hover:text-ink",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className = "", type = "button", ...props },
  ref,
) {
  const sizing = size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-sm";
  return <button ref={ref} type={type} className={`${BUTTON_BASE} ${BUTTON_VARIANTS[variant]} ${sizing} ${className}`} {...props} />;
});

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  size?: "sm" | "md";
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, size = "md", className = "", type = "button", children, ...props },
  ref,
) {
  const sizing = size === "sm" ? "size-7" : "size-9";
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={`inline-flex shrink-0 items-center justify-center rounded-md text-ink-3 transition-colors duration-150 hover:bg-sunk hover:text-ink disabled:opacity-40 ${sizing} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
});

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-rule-strong bg-raised px-1 font-mono text-[10.5px] leading-none text-ink-3">
      {children}
    </kbd>
  );
}

const KIND_STYLE = {
  statute: "text-statute",
  case_law: "text-case",
  pdf: "text-ink-3",
} as const;

/** The typographic marker that distinguishes statutes (§), case law and other sources. */
export function SourceGlyph({ type, className = "" }: { type: string | null | undefined; className?: string }) {
  const kind = sourceKind(type);
  if (kind === "statute") {
    return (
      <span aria-hidden className={`font-serif text-[1.05em] leading-none ${KIND_STYLE.statute} ${className}`}>
        §
      </span>
    );
  }
  const Icon = kind === "case_law" ? Scale : FileText;
  return <Icon aria-hidden size={13} strokeWidth={1.75} className={`${KIND_STYLE[kind]} ${className}`} />;
}

export function SourceTypeLabel({ type }: { type: string | null | undefined }) {
  const kind = sourceKind(type);
  return (
    <span className={`eyebrow inline-flex items-center gap-1.5 ${KIND_STYLE[kind]}`}>
      <SourceGlyph type={kind} />
      {SOURCE_LABEL[kind]}
    </span>
  );
}

export function VerifiedMark({ verified, compact = false }: { verified: boolean; compact?: boolean }) {
  if (verified) {
    return (
      <span className="inline-flex items-center gap-1 text-[12px] text-verify" title="Citation verified against the source database">
        <CircleCheck aria-hidden size={13} strokeWidth={2} />
        {compact ? <span className="sr-only">Verified</span> : "Verified against source"}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[12px] text-caution" title="This citation could not be verified">
      <CircleAlert aria-hidden size={13} strokeWidth={2} />
      {compact ? <span className="sr-only">Unverified</span> : "Not verified"}
    </span>
  );
}

export function SkeletonLines({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2.5 ${className}`} aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton h-3.5" style={{ width: i === lines - 1 ? "62%" : `${92 - i * 4}%` }} />
      ))}
    </div>
  );
}

interface StateProps {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  tone?: "neutral" | "error";
}

export function StatePanel({ title, children, action, tone = "neutral" }: StateProps) {
  return (
    <div role={tone === "error" ? "alert" : undefined} className="mx-auto max-w-md py-16 text-center">
      {tone === "error" && <CircleAlert aria-hidden className="mx-auto mb-4 text-caution" size={22} strokeWidth={1.75} />}
      <h2 className="font-serif text-2xl text-ink">{title}</h2>
      {children && <div className="mt-2 text-[15px] leading-relaxed text-ink-3">{children}</div>}
      {action && <div className="mt-6 flex justify-center gap-2">{action}</div>}
    </div>
  );
}
