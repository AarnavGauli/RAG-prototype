export type DocStatus = "queued" | "processing" | "ready" | "failed";

export interface DocumentItem {
  id: string;
  name: string;
  size_bytes: number;
  page_count: number;
  chunk_count: number;
  status: DocStatus;
  stage: string | null;
  progress: { current: number; total: number } | null;
  error: { code: string; message: string; retryable: boolean } | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  document_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface Citation {
  id: string;
  label: string;
  document_id: string;
  document_name: string;
  page_number: number;
  excerpt: string;
  quote_verified: boolean;
  score: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "ok" | "insufficient_evidence";
  created_at: string;
  citations: Citation[];
  meta: { retrieved: number | null; top_score: number | null; reason: string | null } | null;
}

export interface MessagePage {
  messages: Message[];
  has_more: boolean;
}

export interface CitationDetail extends Citation {
  chunk_text: string;
  char_start: number;
  char_end: number;
  page_image_url: string;
  message_id: string;
}

export interface ProviderStatus {
  provider: string;
  model: string;
  ready: boolean;
  detail: string | null;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  database: boolean;
  indexed_chunks: number;
  embedding: ProviderStatus;
  llm: ProviderStatus;
  limits: { max_upload_mb: number; max_documents: number; max_question_chars: number };
}

export interface EvalReport {
  generated_at: string;
  config: Record<string, string | number>;
  deterministic: {
    retrieval: { hit_at_k: Record<string, number | null>; mrr: number | null; answerable_questions: number };
    abstention: { correct_abstain_rate_on_unanswerable: number | null; false_abstain_rate_on_answerable: number | null };
    citations: { validity_rate: number | null; supports_expected_evidence_rate: number | null };
    answers: { contains_expected_rate: number | null; mean_lexical_groundedness: number | null };
  };
  llm_judged: { disclaimer: string; faithful_rate: number | null; relevant_rate: number | null } | null;
  notes: string[];
  per_question: {
    id: string;
    type: string;
    question: string;
    evidence_rank: number | null;
    top_score: number | null;
    abstained?: boolean;
    error?: string;
  }[];
}

/** A source the user is inspecting: a validated citation, or a plain page of a document. */
export type SourceSelection =
  | { kind: "citation"; citationId: string }
  | { kind: "page"; documentId: string; page: number };
