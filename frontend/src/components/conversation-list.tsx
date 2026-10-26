"use client";

import { useRef, useState } from "react";
import { MessageSquare, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { relativeTime } from "@/lib/format";
import type { Conversation } from "@/lib/types";

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onRename,
  onDelete,
}: {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (c: Conversation) => void;
  onRename: (c: Conversation, title: string) => Promise<void>;
  onDelete: (c: Conversation) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const cancelled = useRef(false);

  async function commit(c: Conversation) {
    if (cancelled.current) {
      cancelled.current = false;
      return;
    }
    const title = draft.trim();
    if (!title || title === c.title) {
      setEditing(null);
      return;
    }
    try {
      await onRename(c, title);
      setEditing(null);
      setRenameError(null);
    } catch {
      setRenameError("Could not rename the conversation.");
    }
  }

  return (
    <ul className="space-y-0.5" aria-label="Conversations">
      {conversations.map((c) => (
        <li key={c.id} className="group relative">
          {editing === c.id ? (
            <form
              className="px-1 py-1"
              onSubmit={(e) => {
                e.preventDefault();
                void commit(c);
              }}
            >
              <label className="sr-only" htmlFor={`rename-${c.id}`}>
                Conversation title
              </label>
              <input
                id={`rename-${c.id}`}
                autoFocus
                value={draft}
                maxLength={200}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => void commit(c)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    cancelled.current = true;
                    setEditing(null);
                    setRenameError(null);
                  }
                }}
                className="h-8 w-full rounded-md border border-accent bg-surface px-2 text-sm"
              />
              {renameError && (
                <p role="alert" className="mt-1 text-xs text-danger">
                  {renameError}
                </p>
              )}
            </form>
          ) : (
            <>
              <button
                type="button"
                onClick={() => onSelect(c)}
                aria-current={c.id === activeId ? "true" : undefined}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2 py-2 pr-16 text-left text-sm hover:bg-surface-2",
                  c.id === activeId && "bg-accent-soft font-medium",
                )}
              >
                <MessageSquare className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{c.title}</span>
                  <span className="block text-xs font-normal text-muted">{relativeTime(c.updated_at)}</span>
                </span>
              </button>
              <div className="absolute right-1 top-1/2 flex -translate-y-1/2 opacity-0 focus-within:opacity-100 group-hover:opacity-100 max-lg:opacity-100">
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Rename ${c.title}`}
                  title="Rename"
                  onClick={() => {
                    cancelled.current = false;
                    setDraft(c.title);
                    setEditing(c.id);
                  }}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="icon" aria-label={`Delete ${c.title}`} title="Delete" onClick={() => onDelete(c)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
