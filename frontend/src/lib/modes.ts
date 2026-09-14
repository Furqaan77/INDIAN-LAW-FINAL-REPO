import { newResearchId } from "./history";

export type ModeId = "research" | "quick" | "statutes" | "cases" | "compare";

export interface ModeDefinition {
  id: ModeId;
  label: string;
  verb: string;
  placeholder: string;
  hint: string;
}

export const MODES: ModeDefinition[] = [
  {
    id: "research",
    label: "Legal research",
    verb: "Research",
    placeholder: "Ask a question about Indian law…",
    hint: "A structured analysis citing the statutes and judgments it relies on.",
  },
  {
    id: "quick",
    label: "Quick answer",
    verb: "Answer",
    placeholder: "Ask a question for a short, cited answer…",
    hint: "Two to four sentences, with the same verified citations.",
  },
  {
    id: "statutes",
    label: "Statute search",
    verb: "Search",
    placeholder: "Search statutory provisions…",
    hint: "Find sections across Central Acts. Retrieval only — no generated answer.",
  },
  {
    id: "cases",
    label: "Case search",
    verb: "Search",
    placeholder: "Search judgments…",
    hint: "Find passages in indexed judgments. Retrieval only — no generated answer.",
  },
  {
    id: "compare",
    label: "Old → New law",
    verb: "Compare",
    placeholder: "e.g. IPC 420, CrPC 438, Evidence Act 65B",
    hint: "Trace a section of the IPC, CrPC or Evidence Act to its new-code counterpart.",
  },
];

const ACT_ALIASES: [string, string][] = [
  ["bharatiya nagarik suraksha sanhita", "bnss"],
  ["bharatiya sakshya adhiniyam", "bsa"],
  ["bharatiya nyaya sanhita", "bns"],
  ["code of criminal procedure", "crpc"],
  ["indian evidence act", "iea"],
  ["indian penal code", "ipc"],
  ["evidence act", "iea"],
  ["penal code", "ipc"],
  ["cr p c", "crpc"],
  ["crpc", "crpc"],
  ["bnss", "bnss"],
  ["bns", "bns"],
  ["bsa", "bsa"],
  ["iea", "iea"],
  ["ipc", "ipc"],
];

/** Parses references like "IPC 420", "Section 438 CrPC" or "s. 65B of the Evidence Act". */
export function parseSectionReference(text: string): { act: string; section: string } | null {
  const normalized = ` ${text.toLowerCase().replace(/[.,;:()]/g, " ").replace(/\s+/g, " ").trim()} `;
  const alias = ACT_ALIASES.find(([name]) => normalized.includes(` ${name} `));
  if (!alias) return null;
  const withoutAct = normalized.replace(` ${alias[0]} `, " ");
  const section = withoutAct.match(/(?:^|\s)(?:section|sec|s)?\s*(\d{1,4}[a-z]{0,2})(?=\s|$)/);
  return section ? { act: alias[1], section: section[1].toUpperCase() } : null;
}

export type Destination = { ok: true; to: string } | { ok: false; message: string };

export function destinationFor(mode: ModeId, text: string): Destination {
  const q = text.trim();
  switch (mode) {
    case "research":
    case "quick":
      return { ok: true, to: `/research/${newResearchId()}?${new URLSearchParams({ q, mode })}` };
    case "statutes":
      return { ok: true, to: `/search?${new URLSearchParams({ q, type: "statute" })}` };
    case "cases":
      return { ok: true, to: `/search?${new URLSearchParams({ q, type: "case_law" })}` };
    case "compare": {
      const reference = parseSectionReference(q);
      return reference
        ? { ok: true, to: `/compare?${new URLSearchParams(reference)}` }
        : { ok: false, message: "Enter a section and its code, such as “IPC 420”, “CrPC 438” or “Evidence Act 65B”." };
    }
  }
}
