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
  source: string;
  score: number | null;
  rerank_score: number | null;
  excerpt: string;
  cited: boolean;
  document: DocumentSummary | null;
  /** Rank of this source in each retriever that found it: semantic, keyword, reference, mapping, subquery_semantic. */
  retrieval_ranks?: Record<string, number> | null;
  /** Why the source was reserved: explicit_reference, mapped_counterpart or case_law_authority. */
  required_reason?: string | null;
  chunk_id?: string | null;
}

export interface CitationCheck {
  proposed: number;
  matched: number;
  rejected: number;
  rejected_quotes: { doc_id: string | null; quote: string }[];
  sources: number;
  sources_verified: number;
  sources_unverified: number;
}

/** Answer engines: the same RAG evidence, a different answer model. */
export type EngineKey = "claude" | "lora_qwen" | "qwen";

export type OutputStatus = "VALID" | "MALFORMED" | "TRUNCATED" | "FAILED";

export interface EngineRun {
  key: EngineKey;
  label: string;
  subtitle: string;
  model: string;
  description?: string;
  role?: string;
  runtime?: string;
  provider: string;
  adapter: string | null;
  adapter_label: string | null;
  experimental: boolean;
  rag: boolean;
  evidence_id?: string | null;
  evidence_reused?: boolean;
  retrieved_sources?: number;
  retrieval_s?: number;
  generation_s?: number | null;
  total_s?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  citation_count?: number;
  verified_citations?: number;
  unverified_citations?: number;
  retry_count: number;
  /** Which attempt's answer is shown (1-based). */
  used_attempt?: number | null;
  /** The reply was malformed, but its answer text was recovered from it. */
  answer_recovered?: boolean;
  /** Nothing could be parsed; the model's raw output is shown instead. */
  raw_output_shown?: boolean;
  output_status: OutputStatus;
  first_output_status?: OutputStatus;
  error?: string | null;
  message?: string | null;
}

export interface EngineStatus extends EngineRun {
  available: boolean;
  detail: string;
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
  /** Present when the answer came from a selected engine (absent in older history entries). */
  engine?: EngineRun | null;
  evidence?: { evidence_id: string | null; reused: boolean; doc_ids: string[] } | null;
  /** Absent in history entries saved before the demo build. */
  citation_check?: CitationCheck | null;
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
