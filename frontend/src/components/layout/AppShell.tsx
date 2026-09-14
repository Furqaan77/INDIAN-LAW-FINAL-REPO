import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { BREAKPOINTS, useMediaQuery } from "../../hooks/useMediaQuery";
import { useHotkey } from "../../hooks/useHotkey";
import { Drawer } from "../Drawer";
import { HistoryPanel } from "../history/HistoryPanel";
import { NAV_ITEMS, TopBar } from "./TopBar";

const RAIL_WIDTH = 272;

export function AppShell() {
  const { pathname } = useLocation();
  const isWide = useMediaQuery(BREAKPOINTS.xl);
  // The persistent rail belongs to the research workspace; everywhere else history is a drawer.
  const railEligible = pathname.startsWith("/research");
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const showRail = railEligible && isWide && !railCollapsed;

  useEffect(() => {
    setDrawerOpen(false);
    window.scrollTo({ top: 0 });
  }, [pathname]);

  const toggleHistory = useCallback(() => {
    if (railEligible && isWide) setRailCollapsed((collapsed) => !collapsed);
    else setDrawerOpen((open) => !open);
  }, [railEligible, isWide]);

  useHotkey("mod+b", toggleHistory);

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-ink px-3 py-2 text-sm text-paper focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <TopBar onToggleHistory={toggleHistory} historyVisible={showRail || drawerOpen} />

      <div className="flex min-h-0 flex-1">
        <AnimatePresence initial={false}>
          {showRail && (
            <motion.aside
              key="history-rail"
              aria-label="Research history"
              className="sticky top-14 h-[calc(100dvh-3.5rem)] shrink-0 overflow-hidden border-r border-rule"
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: RAIL_WIDTH, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="h-full" style={{ width: RAIL_WIDTH }}>
                <HistoryPanel />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>

        <main id="main" className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} side="left" label="Navigation and research history">
        <nav aria-label="Primary" className="border-b border-rule px-2 py-3 md:hidden">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded-md px-2 py-2 text-[15px] ${isActive ? "bg-sunk text-ink" : "text-ink-2 hover:bg-sunk"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="min-h-0 flex-1">
          <HistoryPanel onNavigate={() => setDrawerOpen(false)} />
        </div>
      </Drawer>
    </div>
  );
}
