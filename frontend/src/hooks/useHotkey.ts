import { useEffect, useRef } from "react";

export const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
export const modKeyLabel = isMac ? "⌘" : "Ctrl";

interface HotkeyOptions {
  enabled?: boolean;
  /** Plain-key shortcuts are ignored while typing unless this is set; mod-key shortcuts always fire. */
  allowInInputs?: boolean;
}

/** `combo` is like "/", "escape", "mod+k" or "mod+shift+c" ("mod" is ⌘ on macOS, Ctrl elsewhere). */
export function useHotkey(combo: string, handler: (event: KeyboardEvent) => void, options: HotkeyOptions = {}) {
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  });

  const { enabled = true, allowInInputs = false } = options;

  useEffect(() => {
    if (!enabled) return;
    const parts = combo.toLowerCase().split("+");
    const key = parts.pop() ?? "";
    const needsMod = parts.includes("mod");
    const needsShift = parts.includes("shift");

    const onKeyDown = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod !== needsMod || event.shiftKey !== needsShift || event.altKey) return;
      if (event.key.toLowerCase() !== key) return;
      const target = event.target as HTMLElement | null;
      const typing = !!target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
      if (typing && !needsMod && !allowInInputs) return;
      event.preventDefault();
      handlerRef.current(event);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [combo, enabled, allowInInputs]);
}
