export type SourceType = "statute" | "case_law" | "pdf";

export type ResearchMode = "research" | "quick";

export interface StatuteInfo {
  act_id: string | null;
  act_title: string | null;
  act_long_title: string | null;
  act_year: number | null;
  act_number: string | null;
  section_number: string | null;
  section_heading: string | null;
  enforcement_date: string | null;
  ministry: string | null;
  source_url: string | null;
  has_correspondences: boolean;
}

export interface DocumentSummary {
  doc_id: string;
  title: string;
  source_type: SourceType;
  court: string | null;
  date: string | null;
  judges: string[];
  file_name: string | null;
  statute?: StatuteInfo;
}

interface ChunkLocation {
  doc_id: string;
  title: string;
  source_type: SourceType;
  court: string | null;
  date: string | null;
  section: string | null;
  file_name: string | null;
  page_start: number | null;
  page_end: number | null;
}

export interface Citation extends ChunkLocation {
  number: number;
  excerpt: string;
  passages: string[];
  quotes: string[];
  verified: boolean;
  document: DocumentSummary | null;
}

export interface RetrievedDocument extends ChunkLocation {
  source: "semantic" | "keyword";
  score: number | null;
  rerank_score: number | null;
  excerpt: string;
  cited: boolean;
  document: DocumentSummary | null;
}

export interface ResearchResult {
  question: string;
  mode: ResearchMode;
  answer_markdown: string;
  citations: Citation[];
  retrieved_documents: RetrievedDocument[];
  verified_count: number;
  unverified: string[];
  unmatched_citations: number;
  accuracy_note: string | null;
  error: "retrieval" | "generation" | null;
  models: { llm: string; embedding: string };
  completed_at: number;
}

export type StageId = "semantic" | "keyword" | "ranking" | "drafting" | "verification" | "search";

export interface StageEvent {
  stage: StageId;
  status: "started" | "done" | "failed";
  detail: Record<string, number | string | undefined>;
  at: number;
}

export interface Highlight {
  quote: string;
  start: number;
  end: number;
}

export interface Correspondence {
  direction: "predecessor" | "successor";
  relation: string;
  score: number | null;
  act_id: string | null;
  section_number: string | null;
  official_url: string | null;
  document: DocumentSummary | null;
  full_text: string | null;
}

export interface DocumentDetail extends DocumentSummary {
  full_text: string;
  highlights: Highlight[];
  correspondences?: Correspondence[];
}

export interface SearchResult {
  doc_id: string;
  title: string;
  excerpt: string;
  score: number | null;
  matched_via: "semantic" | "keyword";
  document: DocumentSummary | null;
}

export interface SearchResponse {
  query: string;
  type: "statute" | "case_law";
  results: SearchResult[];
  took_ms: number;
}

export interface CorpusStats {
  documents: number;
  by_source_type: Partial<Record<SourceType, number>>;
  acts: number;
  passages: number | null;
  models: { llm: string; embedding: string };
}

export interface MappedAct {
  act_id: string;
  act_title: string;
  counterpart_act_id: string;
  counterpart_act_title: string | null;
  direction: "predecessor" | "successor";
  mapped_sections: number;
}

export interface LawMapResponse {
  source: DocumentSummary & { full_text: string };
  correspondences: Correspondence[];
}

export interface ActSections {
  act_id: string;
  act_title: string | null;
  sections: { doc_id: string; section_number: string | null; section_heading: string | null }[];
}
