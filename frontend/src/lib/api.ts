import type {
  CitationDetail,
  Conversation,
  DocumentItem,
  EvalReport,
  Health,
  Message,
  MessagePage,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
  get isNetwork() {
    return this.code === "network_error";
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    if (body?.error) return new ApiError(body.error.message, body.error.code, res.status, body.error.details);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(`Request failed (HTTP ${res.status}).`, "http_error", res.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      credentials: "same-origin",
      ...init,
      headers: init?.body ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
    });
  } catch {
    throw new ApiError("Cannot reach the PDF Intelligence server. Check that the backend is running.", "network_error", 0);
  }
  if (!res.ok) throw await toApiError(res);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  health: () => request<Health>("/health"),
  listDocuments: () => request<DocumentItem[]>("/documents"),
  getDocument: (id: string) => request<DocumentItem>(`/documents/${id}`),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  retryDocument: (id: string) => request<DocumentItem>(`/documents/${id}/retry`, { method: "POST" }),

  /** XHR (not fetch) so the browser reports real upload progress. */
  uploadDocument(file: File, onProgress?: (fraction: number) => void): Promise<DocumentItem> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/documents`);
      xhr.responseType = "json";
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onerror = () =>
        reject(new ApiError("Upload failed: cannot reach the server.", "network_error", 0));
      xhr.onload = () => {
        const body = xhr.response;
        if (xhr.status >= 200 && xhr.status < 300) return resolve(body as DocumentItem);
        const err = body?.error;
        reject(new ApiError(err?.message ?? `Upload failed (HTTP ${xhr.status}).`, err?.code ?? "http_error", xhr.status, err?.details));
      };
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },

  listConversations: () => request<Conversation[]>("/conversations"),
  createConversation: (body: { title?: string; document_ids?: string[] }) =>
    request<Conversation>("/conversations", { method: "POST", body: JSON.stringify(body) }),
  updateConversation: (id: string, body: { title?: string; document_ids?: string[] }) =>
    request<Conversation>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" }),
  listMessages: (id: string, before?: string) =>
    request<MessagePage>(`/conversations/${id}/messages?limit=50${before ? `&before=${before}` : ""}`),
  ask: (id: string, content: string) =>
    request<{ user_message: Message; assistant_message: Message }>(`/conversations/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  getCitation: (id: string) => request<CitationDetail>(`/citations/${id}`),
  pageImageUrl: (documentId: string, page: number) => `${BASE}/documents/${documentId}/pages/${page}/image`,

  latestEvaluation: () => request<EvalReport>("/evaluation/report"),
  runEvaluation: () => request<EvalReport>("/evaluation/run", { method: "POST" }),
};

/** Maps API/network errors to user-facing guidance. */
export function describeError(err: unknown): { title: string; message: string; retryable: boolean } {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "network_error":
        return { title: "Connection problem", message: err.message, retryable: true };
      case "llm_not_configured":
      case "embedding_not_configured":
        return { title: "AI provider not configured", message: err.message, retryable: false };
      case "llm_auth_failed":
      case "embedding_auth_failed":
        return { title: "AI provider rejected the credentials", message: err.message, retryable: false };
      case "llm_rate_limited":
      case "rate_limited":
        return { title: "Rate limited", message: err.message, retryable: true };
      case "no_ready_documents":
        return { title: "No indexed documents", message: err.message, retryable: false };
      default:
        return { title: "Something went wrong", message: err.message, retryable: err.status >= 500 };
    }
  }
  return { title: "Something went wrong", message: "An unexpected error occurred.", retryable: true };
}
