"use client";

import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BarChart3, FileStack, Layers, Menu, MessageSquarePlus, PanelRightClose } from "lucide-react";
import { Composer, EmptyConversation, MessageList, type PendingTurn, type SendFailure } from "@/components/chat";
import { ConversationList } from "@/components/conversation-list";
import { DocumentRow } from "@/components/document-item";
import { ScopeDialog } from "@/components/scope-dialog";
import { SourcePanel } from "@/components/source-panel";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Notice } from "@/components/ui/notice";
import { UploadZone } from "@/components/upload-zone";
import { useDocuments } from "@/hooks/use-documents";
import { useMediaQuery } from "@/hooks/use-media-query";
import { api, ApiError, describeError } from "@/lib/api";
import type { Citation, Conversation, DocumentItem, Health, Message, SourceSelection } from "@/lib/types";

const sourceKey = (s: SourceSelection) => (s.kind === "citation" ? s.citationId : `${s.documentId}:${s.page}`);

export function Workspace() {
  const [sessionReady, setSessionReady] = useState(false);
  const { docs, error: docsError, refresh: refreshDocs } = useDocuments(sessionReady);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<ApiError | null>(null);

  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [draftScope, setDraftScope] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [failure, setFailure] = useState<SendFailure | null>(null);

  const [source, setSource] = useState<SourceSelection | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [docToDelete, setDocToDelete] = useState<DocumentItem | null>(null);
  const [convToDelete, setConvToDelete] = useState<Conversation | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const wide = useMediaQuery("(min-width: 1280px)");
  const desktop = useMediaQuery("(min-width: 1024px)");
  const loadToken = useRef(0);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
      setHealthError(null);
    } catch (e) {
      setHealthError(e instanceof ApiError ? e : null);
    }
  }, []);
  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations());
    } catch {
      setConversations((c) => c ?? []);
    }
  }, []);

  // The health call establishes the session cookie, so it must finish before any other request is sent
  // (parallel cookie-less requests would each be given a different session).
  useEffect(() => {
    let alive = true;
    api
      .health()
      .then((h) => alive && setHealth(h))
      .catch((e) => alive && setHealthError(e instanceof ApiError ? e : null))
      .finally(() => alive && setSessionReady(true));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!sessionReady) return;
    let alive = true;
    api
      .listConversations()
      .then((c) => alive && setConversations(c))
      .catch(() => alive && setConversations([]));
    return () => {
      alive = false;
    };
  }, [sessionReady]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const readyDocs = useMemo(() => (docs ?? []).filter((d) => d.status === "ready"), [docs]);
  const active = conversations?.find((c) => c.id === activeId) ?? null;
  const scopeIds = active ? active.document_ids : draftScope;
  const scopeLabel =
    scopeIds.length === 0 ? "All documents" : `${scopeIds.length} document${scopeIds.length === 1 ? "" : "s"}`;
  const sending = pending !== null;

  // ---- conversations ---------------------------------------------------------------------------
  const openConversation = useCallback(async (c: Conversation | null) => {
    const token = ++loadToken.current;
    setActiveId(c?.id ?? null);
    setFailure(null);
    setSource(null);
    setSidebarOpen(false);
    setMessages([]);
    setHasMore(false);
    if (!c) return;
    setLoadingMessages(true);
    try {
      const page = await api.listMessages(c.id);
      if (token !== loadToken.current) return;
      setMessages(page.messages);
      setHasMore(page.has_more);
    } catch (e) {
      if (token === loadToken.current) setFailure({ question: "(loading history)", error: e });
    } finally {
      if (token === loadToken.current) setLoadingMessages(false);
    }
  }, []);

  async function loadMore() {
    if (!activeId || messages.length === 0) return;
    setLoadingMore(true);
    try {
      const page = await api.listMessages(activeId, messages[0]!.id);
      setMessages((m) => [...page.messages, ...m]);
      setHasMore(page.has_more);
    } catch (e) {
      setActionError(describeError(e).message);
    } finally {
      setLoadingMore(false);
    }
  }

  const send = useCallback(
    async (question: string) => {
      setFailure(null);
      setPending({ question });
      let convId = activeId;
      let created = false;
      try {
        if (!convId) {
          const c = await api.createConversation({ document_ids: draftScope });
          convId = c.id;
          created = true;
          setConversations((list) => [c, ...(list ?? [])]);
          setActiveId(c.id);
          loadToken.current++;
        }
        const { user_message, assistant_message } = await api.ask(convId, question);
        setMessages((m) => [...m, user_message, assistant_message]);
        void refreshConversations();
      } catch (e) {
        if (created && convId) {
          // don't leave an empty conversation behind for a question that was never answered
          await api.deleteConversation(convId).catch(() => undefined);
          setConversations((list) => (list ?? []).filter((c) => c.id !== convId));
          setActiveId(null);
        }
        setFailure({ question, error: e });
        if (e instanceof ApiError && (e.code.startsWith("llm_") || e.code === "no_ready_documents")) void refreshHealth();
      } finally {
        setPending(null);
      }
    },
    [activeId, draftScope, refreshConversations, refreshHealth],
  );

  async function saveScope(ids: string[]) {
    if (active) {
      const updated = await api.updateConversation(active.id, { document_ids: ids });
      setConversations((list) => (list ?? []).map((c) => (c.id === updated.id ? updated : c)));
    } else {
      setDraftScope(ids);
    }
    setScopeOpen(false);
  }

  async function renameConversation(c: Conversation, title: string) {
    const updated = await api.updateConversation(c.id, { title });
    setConversations((list) => (list ?? []).map((x) => (x.id === c.id ? updated : x)));
  }

  async function confirmDeleteConversation() {
    if (!convToDelete) return;
    setDeleting(true);
    try {
      await api.deleteConversation(convToDelete.id);
      setConversations((list) => (list ?? []).filter((c) => c.id !== convToDelete.id));
      if (convToDelete.id === activeId) void openConversation(null);
      setToast("Conversation deleted");
    } catch (e) {
      setActionError(describeError(e).message);
    } finally {
      setDeleting(false);
      setConvToDelete(null);
    }
  }

  // ---- documents -------------------------------------------------------------------------------
  async function confirmDeleteDocument() {
    if (!docToDelete) return;
    setDeleting(true);
    try {
      await api.deleteDocument(docToDelete.id);
      await Promise.all([refreshDocs(), refreshConversations(), refreshHealth()]);
      setDraftScope((s) => s.filter((id) => id !== docToDelete.id));
      if (source && (source.kind === "page" ? source.documentId === docToDelete.id : false)) setSource(null);
      setToast(`Deleted “${docToDelete.name}”`);
    } catch (e) {
      setActionError(describeError(e).message);
    } finally {
      setDeleting(false);
      setDocToDelete(null);
    }
  }

  async function retryDocument(doc: DocumentItem) {
    setRetrying(doc.id);
    try {
      await api.retryDocument(doc.id);
      await refreshDocs();
    } catch (e) {
      setActionError(describeError(e).message);
    } finally {
      setRetrying(null);
    }
  }

  const openCitation = useCallback((c: Citation) => setSource({ kind: "citation", citationId: c.id }), []);

  // ---- layout ----------------------------------------------------------------------------------
  const limits = health?.limits;
  const atDocLimit = limits ? (docs?.length ?? 0) >= limits.max_documents : false;

  const sidebar = (
    <div className="flex h-full min-h-0 flex-col bg-paper">
      <div className="flex items-center justify-between px-4 pb-2 pt-4">
        <h1 className="font-serif text-lg font-semibold tracking-tight">PDF Intelligence</h1>
      </div>
      <div className="px-3 pb-3">
        <Button variant="primary" className="w-full" onClick={() => void openConversation(null)}>
          <MessageSquarePlus className="h-4 w-4" aria-hidden /> New conversation
        </Button>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        <section aria-labelledby="docs-heading">
          <h2 id="docs-heading" className="mb-2 flex items-center gap-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-muted">
            <FileStack className="h-3.5 w-3.5" aria-hidden /> Documents {docs && <span className="font-normal">({docs.length})</span>}
          </h2>
          <UploadZone
            maxMb={limits?.max_upload_mb ?? 20}
            disabled={atDocLimit || !sessionReady}
            disabledReason={sessionReady ? `Document limit reached (${limits?.max_documents}). Delete one to upload more.` : "Connecting…"}
            onUploaded={() => void refreshDocs()}
          />
          {docsError && (
            <Notice tone="error" title="Could not load documents" className="mt-2" action={<Button size="sm" onClick={() => void refreshDocs()}>Retry</Button>}>
              {docsError.message}
            </Notice>
          )}
          <ul className="mt-2 space-y-1.5" aria-label="Documents">
            {docs === null && !docsError && (
              <>
                <li className="skeleton h-14" aria-hidden />
                <li className="skeleton h-14" aria-hidden />
              </>
            )}
            {docs?.map((d) => (
              <DocumentRow
                key={d.id}
                doc={d}
                retrying={retrying === d.id}
                onPreview={(doc) => {
                  setSource({ kind: "page", documentId: doc.id, page: 1 });
                  setSidebarOpen(false);
                }}
                onDelete={setDocToDelete}
                onRetry={retryDocument}
              />
            ))}
          </ul>
          {docs?.length === 0 && <p className="mt-2 px-1 text-xs text-muted">No documents yet.</p>}
        </section>

        <section aria-labelledby="conv-heading">
          <h2 id="conv-heading" className="mb-1 px-1 text-xs font-semibold uppercase tracking-wide text-muted">
            Conversations
          </h2>
          {conversations === null ? (
            <div className="space-y-1.5" aria-label="Loading conversations">
              <div className="skeleton h-10" />
              <div className="skeleton h-10" />
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-1 text-xs text-muted" data-testid="no-conversations">
              No conversations yet. Ask your first question to start one.
            </p>
          ) : (
            <ConversationList
              conversations={conversations}
              activeId={activeId}
              onSelect={(c) => void openConversation(c)}
              onRename={renameConversation}
              onDelete={setConvToDelete}
            />
          )}
        </section>
      </div>

      <footer className="border-t border-line px-4 py-3 text-xs text-muted">
        <Link href="/evaluation" className="inline-flex items-center gap-1.5 hover:text-ink">
          <BarChart3 className="h-3.5 w-3.5" aria-hidden /> RAG evaluation
        </Link>
        <p className="mt-1">Local single-user app · data stays on this machine</p>
      </footer>
    </div>
  );

  const showEmpty = !activeId && !pending && !failure;
  const composerDisabled = readyDocs.length === 0;

  return (
    <div className="flex h-dvh overflow-hidden">
      {desktop ? (
        <nav aria-label="Library" className="w-80 shrink-0 border-r border-line">
          {sidebar}
        </nav>
      ) : (
        <Dialog.Root open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
            <Dialog.Content aria-describedby={undefined} className="fixed inset-y-0 left-0 z-50 w-[min(22rem,90vw)] border-r border-line shadow-xl">
              <Dialog.Title className="sr-only">Library</Dialog.Title>
              {sidebar}
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      )}

      <main className="flex min-w-0 flex-1 flex-col" aria-label="Conversation area">
        <header className="flex items-center gap-2 border-b border-line px-3 py-2.5">
          {!desktop && (
            <Button variant="ghost" size="icon" aria-label="Open library" onClick={() => setSidebarOpen(true)}>
              <Menu className="h-5 w-5" />
            </Button>
          )}
          <h2 className="min-w-0 flex-1 truncate font-serif text-base font-semibold">{active?.title ?? "New conversation"}</h2>
          <Button size="sm" onClick={() => setScopeOpen(true)} aria-label={`Document scope: ${scopeLabel}. Change`}>
            <Layers className="h-4 w-4" aria-hidden /> {scopeLabel}
          </Button>
          {source && wide && (
            <Button variant="ghost" size="icon" aria-label="Hide source panel" onClick={() => setSource(null)}>
              <PanelRightClose className="h-4 w-4" />
            </Button>
          )}
        </header>

        <div className="space-y-2 px-4 pt-3 empty:hidden">
          {healthError && (
            <Notice tone="error" title="Backend unreachable" action={<Button size="sm" onClick={() => void refreshHealth()}>Check again</Button>}>
              {healthError.message}
            </Notice>
          )}
          {health && !health.llm.ready && (
            <Notice tone="warn" title="AI provider not configured">
              {health.llm.detail} Documents can still be uploaded and indexed; questions need a configured LLM. See the README, “Configure an AI provider”.
            </Notice>
          )}
          {health && !health.embedding.ready && (
            <Notice tone="warn" title="Embedding provider not ready">
              {health.embedding.detail}
            </Notice>
          )}
          {actionError && (
            <Notice tone="error" title="Action failed" action={<Button size="sm" variant="ghost" onClick={() => setActionError(null)}>Dismiss</Button>}>
              {actionError}
            </Notice>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {showEmpty ? (
            <EmptyConversation hasReadyDocs={readyDocs.length > 0} hasDocs={(docs?.length ?? 0) > 0} onSuggest={(q) => void send(q)} />
          ) : (
            <MessageList
              messages={messages}
              loading={loadingMessages}
              hasMore={hasMore}
              loadingMore={loadingMore}
              pending={pending}
              failure={failure}
              onLoadMore={() => void loadMore()}
              onOpenCitation={openCitation}
              onRetry={() => failure && void send(failure.question)}
              onDismissFailure={() => setFailure(null)}
            />
          )}
        </div>

        <Composer
          disabled={composerDisabled}
          disabledReason={docs?.length ? "Waiting for a document to finish indexing…" : "Upload a PDF to start asking questions"}
          sending={sending}
          maxChars={limits?.max_question_chars ?? 2000}
          draft={draft}
          onDraftChange={setDraft}
          onSend={(q) => void send(q)}
        />
      </main>

      {source &&
        (wide ? (
          <div className="w-[26rem] shrink-0 border-l border-line">
            <SourcePanel key={sourceKey(source)} selection={source} documents={docs ?? []} onClose={() => setSource(null)} />
          </div>
        ) : (
          <Dialog.Root open onOpenChange={(o) => !o && setSource(null)}>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
              <Dialog.Content aria-describedby={undefined} className="fixed inset-y-0 right-0 z-50 w-full max-w-md border-l border-line shadow-xl">
                <Dialog.Title className="sr-only">Source inspector</Dialog.Title>
                <SourcePanel key={sourceKey(source)} selection={source} documents={docs ?? []} onClose={() => setSource(null)} />
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        ))}

      <ScopeDialog open={scopeOpen} documents={docs ?? []} selected={scopeIds} onClose={() => setScopeOpen(false)} onSave={saveScope} />
      <ConfirmDialog
        open={docToDelete !== null}
        title="Delete this document?"
        description={`“${docToDelete?.name ?? ""}” will be permanently removed, along with its extracted text, search index entries and the citations that point to it.`}
        confirmLabel="Delete document"
        busy={deleting}
        onConfirm={() => void confirmDeleteDocument()}
        onCancel={() => setDocToDelete(null)}
      />
      <ConfirmDialog
        open={convToDelete !== null}
        title="Delete this conversation?"
        description={`“${convToDelete?.title ?? ""}” and all of its messages will be permanently removed.`}
        confirmLabel="Delete conversation"
        busy={deleting}
        onConfirm={() => void confirmDeleteConversation()}
        onCancel={() => setConvToDelete(null)}
      />
      {toast && (
        <div role="status" className="fixed bottom-24 left-1/2 z-[60] -translate-x-1/2 rounded-lg bg-ink px-4 py-2 text-sm text-paper shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}
