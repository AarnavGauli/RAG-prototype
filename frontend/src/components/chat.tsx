"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, BookOpenCheck, FileSearch, FolderOpen, Loader2, RotateCw, SearchX } from "lucide-react";
import { AnswerMarkdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { describeError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Citation, Message } from "@/lib/types";

export interface PendingTurn {
  question: string;
}

export interface SendFailure {
  question: string;
  error: unknown;
}

function UserBubble({ message }: { message: Message }) {
  return (
    <div className="flex justify-end" data-testid="user-message">
      <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-sm text-accent-ink">
        {message.content}
      </p>
    </div>
  );
}

function AssistantBubble({ message, onOpenCitation }: { message: Message; onOpenCitation: (c: Citation) => void }) {
  const insufficient = message.status === "insufficient_evidence";
  return (
    <article className="flex gap-3" data-testid="assistant-message" data-status={message.status} aria-label="Answer">
      <div
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          insufficient ? "bg-warn-soft text-warn" : "bg-accent-soft text-accent",
        )}
        aria-hidden
      >
        {insufficient ? <SearchX className="h-4 w-4" /> : <BookOpenCheck className="h-4 w-4" />}
      </div>
      <div className="min-w-0 flex-1">
        {insufficient && (
          <p className="mb-1.5 inline-flex items-center gap-1.5 rounded-full bg-warn-soft px-2.5 py-0.5 text-xs font-medium text-warn">
            Insufficient evidence · no sources cited
          </p>
        )}
        <AnswerMarkdown content={message.content} citations={message.citations} onOpenCitation={onOpenCitation} />
        {insufficient && (
          <p className="mt-2 text-xs text-muted">
            The retrieved passages did not support an answer
            {message.meta?.retrieved === 0 ? " (nothing relevant was found)" : ""}. Try rephrasing, or check that the right
            documents are in scope.
          </p>
        )}
        {message.citations.length > 0 && (
          <div className="mt-3" data-testid="citations">
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Sources (validated against retrieved passages)</p>
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {message.citations.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => onOpenCitation(c)}
                    data-testid="citation-card"
                    className="flex h-full w-full flex-col gap-1 rounded-lg border border-line bg-surface p-2.5 text-left text-xs transition-colors hover:border-accent hover:bg-accent-soft"
                  >
                    <span className="flex items-center gap-1.5 font-medium">
                      <span className="rounded bg-accent-soft px-1.5 py-0.5 text-accent">{c.label}</span>
                      <span className="min-w-0 truncate">{c.document_name}</span>
                      <span className="shrink-0 text-muted">· p. {c.page_number}</span>
                    </span>
                    <span className="line-clamp-2 text-muted">{c.excerpt}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </article>
  );
}

function PendingAnswer() {
  return (
    <div className="flex gap-3" role="status" aria-live="polite" data-testid="answer-pending">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      </div>
      <div className="flex-1 space-y-2 pt-1">
        <p className="text-sm text-muted">Retrieving passages and generating an answer…</p>
        <div className="skeleton h-3 w-11/12" />
        <div className="skeleton h-3 w-9/12" />
      </div>
    </div>
  );
}

export function MessageList({
  messages,
  loading,
  hasMore,
  loadingMore,
  pending,
  failure,
  onLoadMore,
  onOpenCitation,
  onRetry,
  onDismissFailure,
}: {
  messages: Message[];
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  pending: PendingTurn | null;
  failure: SendFailure | null;
  onLoadMore: () => void;
  onOpenCitation: (c: Citation) => void;
  onRetry: () => void;
  onDismissFailure: () => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const count = messages.length;
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [count, pending, failure]);

  if (loading) {
    return (
      <div className="space-y-4 p-6" aria-label="Loading messages">
        <div className="skeleton ml-auto h-9 w-1/3" />
        <div className="skeleton h-20 w-3/4" />
      </div>
    );
  }
  const err = failure ? describeError(failure.error) : null;
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6" role="log" aria-label="Conversation">
      {hasMore && (
        <div className="text-center">
          <Button size="sm" onClick={onLoadMore} disabled={loadingMore}>
            {loadingMore ? "Loading…" : "Load earlier messages"}
          </Button>
        </div>
      )}
      {messages.map((m) =>
        m.role === "user" ? <UserBubble key={m.id} message={m} /> : <AssistantBubble key={m.id} message={m} onOpenCitation={onOpenCitation} />,
      )}
      {pending && (
        <>
          <div className="flex justify-end" data-testid="user-message">
            <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-sm text-accent-ink">{pending.question}</p>
          </div>
          <PendingAnswer />
        </>
      )}
      {failure && err && (
        <Notice
          tone="error"
          title={err.title}
          action={
            <div className="flex gap-2">
              {err.retryable && (
                <Button size="sm" onClick={onRetry}>
                  <RotateCw className="h-3.5 w-3.5" aria-hidden /> Retry
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={onDismissFailure}>
                Dismiss
              </Button>
            </div>
          }
        >
          <p>{err.message}</p>
          <p className="mt-1 italic">Your question was not saved: “{failure.question}”</p>
        </Notice>
      )}
      <div ref={endRef} />
    </div>
  );
}

export function EmptyConversation({
  hasReadyDocs,
  hasDocs,
  onSuggest,
}: {
  hasReadyDocs: boolean;
  hasDocs: boolean;
  onSuggest: (q: string) => void;
}) {
  return (
    <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center px-6 text-center" data-testid="empty-state">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-accent">
        {hasReadyDocs ? <FileSearch className="h-6 w-6" aria-hidden /> : <FolderOpen className="h-6 w-6" aria-hidden />}
      </div>
      <h2 className="font-serif text-2xl font-semibold">
        {hasReadyDocs ? "Ask your documents anything" : hasDocs ? "Waiting for indexing" : "Start by adding a PDF"}
      </h2>
      <p className="mt-2 text-sm text-muted">
        {hasReadyDocs
          ? "Answers are grounded in passages retrieved from your PDFs, and every claim links back to the page it came from."
          : hasDocs
            ? "Your documents are still being processed. You can ask questions as soon as one shows as indexed."
            : "Upload a PDF from the sidebar. It will be extracted, split into passages and indexed locally before you can ask questions."}
      </p>
      {hasReadyDocs && (
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {["Summarize the key points", "What are the main figures and dates?"].map((q) => (
            <Button key={q} size="sm" onClick={() => onSuggest(q)}>
              {q}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Composer({
  disabled,
  disabledReason,
  sending,
  maxChars,
  draft,
  onDraftChange,
  onSend,
}: {
  disabled: boolean;
  disabledReason?: string;
  sending: boolean;
  maxChars: number;
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: (q: string) => void;
}) {
  const text = draft;
  const tooLong = text.length > maxChars;
  const canSend = !disabled && !sending && text.trim().length > 0 && !tooLong;

  function submit() {
    if (!canSend) return;
    onSend(text.trim());
    onDraftChange("");
  }

  return (
    <form
      className="mx-auto w-full max-w-3xl px-4 pb-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="rounded-2xl border border-line bg-surface shadow-sm focus-within:border-accent">
        <label htmlFor="question" className="sr-only">
          Ask a question about your documents
        </label>
        <textarea
          id="question"
          value={text}
          rows={2}
          disabled={disabled}
          placeholder={disabled ? (disabledReason ?? "Add a document to start") : "Ask a question about your documents…"}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          aria-describedby="composer-hint"
          className="block w-full resize-none rounded-2xl bg-transparent px-4 pt-3 text-sm outline-none placeholder:text-muted disabled:cursor-not-allowed"
        />
        <div className="flex items-center justify-between px-3 pb-2">
          <p id="composer-hint" className={cn("text-xs", tooLong ? "text-danger" : "text-muted")}>
            {tooLong ? `Too long: ${text.length}/${maxChars}` : "Enter to send · Shift+Enter for a new line"}
          </p>
          <Button type="submit" variant="primary" size="icon" aria-label="Send question" disabled={!canSend}>
            {sending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ArrowUp className="h-4 w-4" aria-hidden />}
          </Button>
        </div>
      </div>
    </form>
  );
}
