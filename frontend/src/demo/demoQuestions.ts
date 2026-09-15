/**
 * Curated demo questions. Each was run against the current corpus before being added (retrieval finds the
 * governing sources and the Claude engine answers with verified citations, or — for the last one — correctly
 * reports that the evidence is insufficient). No expected answers are stored: the live system answers.
 * Edit freely; `href` opens a page other than the research workspace.
 */
export interface DemoQuestion {
  id: string;
  capability: string;
  question: string;
  /** What the audience should notice. */
  shows: string;
  href?: string;
}

export const DEMO_QUESTIONS: DemoQuestion[] = [
  {
    id: "procedure-limitation",
    capability: "Procedural question",
    question: "What is the limitation period for filing a complaint under Section 138 of the Negotiable Instruments Act?",
    shows: "Statute plus judgments in one evidence set. Switch engines to see the same evidence id; watch for rejected quotations.",
  },
  {
    id: "punishment",
    capability: "Punishment",
    question: "What is the punishment for dishonour of a cheque under Section 138 of the Negotiable Instruments Act?",
    shows: "An explicit section reference retrieved exactly, with the quoted penalty verified against the statute text.",
  },
  {
    id: "multiple-sections",
    capability: "Multiple sections",
    question: "How do Sections 138 and 142 of the Negotiable Instruments Act work together when a cheque is dishonoured?",
    shows: "Two provisions reserved in the evidence and cited separately, each opened in the document reader.",
  },
  {
    id: "old-new-law",
    capability: "Old law → new law",
    question: "Which section of the Bharatiya Nagarik Suraksha Sanhita corresponds to anticipatory bail under Section 438 of the Code of Criminal Procedure?",
    shows: "Old/new-law mapping pulls the BNSS counterpart into the evidence alongside the CrPC section.",
  },
  {
    id: "definition",
    capability: "Legal definition",
    question: "How does Section 415 of the Indian Penal Code define cheating?",
    shows: "A definition quoted from the section itself; the evidence panel shows how each source was found.",
  },
  {
    id: "section-identification",
    capability: "Section identification",
    question: "What section of the Motor Vehicles Act governs how speed limits are fixed for vehicles on Indian roads?",
    shows: "Finding the right provision among 38,000+ statutory sections from a plain-language question.",
  },
  {
    id: "case-law",
    capability: "Case law",
    question: "Can a cheque given as security, rather than for an existing debt, still attract Section 138 liability?",
    shows: "Judgments with differing reasoning, each quotation traced to its court decision.",
  },
  {
    id: "insufficient-evidence",
    capability: "Insufficient evidence",
    question: "Under Indian law, what is the standard warranty period for a spacecraft launch services contract?",
    shows:
      "Nothing in the corpus answers this. Claude says so instead of inventing law. The small local models may still guess — a clear example of why LoRA Qwen is experimental.",
  },
  {
    id: "law-map",
    capability: "Old law → new law map",
    question: "IPC Section 420 → Bharatiya Nyaya Sanhita",
    shows: "Side-by-side texts from the published section correspondences, with the differences marked.",
    href: "/compare?act=ipc&section=420",
  },
];
