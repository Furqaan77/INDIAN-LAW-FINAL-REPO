import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";

// The home page ships in the initial bundle; heavier routes (Markdown rendering,
// the document reader, the diff) load on first visit.
export const router = createBrowserRouter([
  {
    element: <AppShell />,
    // Shown only for the instant a lazily loaded route's code is fetched on a direct page load.
    hydrateFallbackElement: <div className="min-h-dvh bg-paper" />,
    children: [
      { path: "/", element: <HomePage /> },
      {
        path: "/research/:id",
        lazy: async () => ({ Component: (await import("./pages/ResearchPage")).ResearchPage }),
      },
      {
        path: "/search",
        lazy: async () => ({ Component: (await import("./pages/SearchPage")).SearchPage }),
      },
      {
        path: "/source/:docId",
        lazy: async () => ({ Component: (await import("./pages/SourcePage")).SourcePage }),
      },
      {
        path: "/compare",
        lazy: async () => ({ Component: (await import("./pages/ComparePage")).ComparePage }),
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
