import { Moon, PanelLeft, Sun } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { modKeyLabel } from "../../hooks/useHotkey";
import { setTheme, useTheme } from "../../lib/theme";
import { IconButton } from "../primitives";

export const NAV_ITEMS = [
  { to: "/", label: "Research", end: true },
  { to: "/search", label: "Search", end: false },
  { to: "/compare", label: "Old → New law", end: false },
] as const;

export function Wordmark() {
  return (
    <Link to="/" className="group inline-flex items-center gap-2.5 rounded-md" aria-label="IndianLawGPT home">
      <span
        aria-hidden
        className="inline-flex size-7 items-center justify-center rounded-[7px] bg-ink font-serif text-[17px] leading-none text-paper transition-transform duration-300 group-hover:-rotate-6"
      >
        §
      </span>
      <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">
        IndianLaw<span className="font-normal text-ink-3">GPT</span>
      </span>
    </Link>
  );
}

export function TopBar({ onToggleHistory, historyVisible }: { onToggleHistory: () => void; historyVisible: boolean }) {
  const theme = useTheme();
  return (
    <header className="sticky top-0 z-40 border-b border-rule bg-paper/88 backdrop-blur-md supports-[backdrop-filter]:bg-paper/75">
      <div className="flex h-14 items-center gap-3 px-3 sm:px-4">
        <IconButton
          label={`${historyVisible ? "Hide" : "Show"} research history (${modKeyLabel}B)`}
          onClick={onToggleHistory}
          aria-expanded={historyVisible}
        >
          <PanelLeft aria-hidden size={17} strokeWidth={1.6} />
        </IconButton>
        <Wordmark />

        <nav aria-label="Primary" className="ml-6 hidden h-full items-stretch gap-1 md:flex">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `relative flex items-center px-2.5 text-[13.5px] transition-colors duration-150 after:absolute after:inset-x-2.5 after:bottom-0 after:h-[1.5px] after:transition-colors ${
                  isActive ? "text-ink after:bg-accent" : "text-ink-3 after:bg-transparent hover:text-ink"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1">
          <IconButton
            label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun aria-hidden size={16} strokeWidth={1.6} /> : <Moon aria-hidden size={16} strokeWidth={1.6} />}
          </IconButton>
        </div>
      </div>
    </header>
  );
}
