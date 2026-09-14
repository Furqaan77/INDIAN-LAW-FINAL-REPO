import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

type Side = "left" | "right" | "bottom";

const PANEL_POSITION: Record<Side, string> = {
  left: "inset-y-0 left-0 h-full w-[min(88vw,360px)] border-r",
  right: "inset-y-0 right-0 h-full w-[min(92vw,480px)] border-l",
  bottom: "inset-x-0 bottom-0 max-h-[88dvh] rounded-t-2xl border-t",
};

const OFFSCREEN: Record<Side, { x?: string; y?: string }> = {
  left: { x: "-100%" },
  right: { x: "100%" },
  bottom: { y: "100%" },
};

const FOCUSABLE = 'a[href], button:not([disabled]), input, textarea, select, [tabindex]:not([tabindex="-1"])';

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  side: Side;
  label: string;
  children: ReactNode;
}

/** Modal side sheet: traps focus, closes on Escape or backdrop click, restores focus on close. */
export function Drawer({ open, onClose, side, label, children }: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusTimer = window.setTimeout(() => panelRef.current?.focus(), 20);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = [...panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus?.();
    };
  }, [open]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
          <motion.div
            className="absolute inset-0 bg-[rgb(20_18_12/0.32)] backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={label}
            tabIndex={-1}
            className={`absolute flex flex-col overflow-hidden border-rule bg-paper shadow-float outline-none ${PANEL_POSITION[side]}`}
            initial={OFFSCREEN[side]}
            animate={{ x: 0, y: 0 }}
            exit={OFFSCREEN[side]}
            transition={{ duration: 0.34, ease: [0.22, 1, 0.36, 1] }}
          >
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
