"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { DocumentItem } from "@/lib/types";

export function ScopeDialog({
  open,
  documents,
  selected,
  onClose,
  onSave,
}: {
  open: boolean;
  documents: DocumentItem[];
  selected: string[];
  onClose: () => void;
  onSave: (ids: string[]) => Promise<void>;
}) {
  const [draft, setDraft] = useState<string[]>(selected);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = documents.filter((d) => d.status === "ready");

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        if (o) {
          setDraft(selected);
          setError(null);
        } else onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-surface p-5 shadow-xl">
          <Dialog.Title className="font-serif text-lg font-semibold">Documents in scope</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-muted">
            Answers will only use the documents you tick. Leave all unticked to search every document.
          </Dialog.Description>
          <ul className="mt-4 max-h-64 space-y-1 overflow-y-auto">
            {ready.length === 0 && <li className="text-sm text-muted">No indexed documents yet.</li>}
            {ready.map((d) => (
              <li key={d.id}>
                <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-[var(--accent)]"
                    checked={draft.includes(d.id)}
                    onChange={(e) => setDraft((cur) => (e.target.checked ? [...cur, d.id] : cur.filter((x) => x !== d.id)))}
                  />
                  <span className="truncate">{d.name}</span>
                </label>
              </li>
            ))}
          </ul>
          {error && (
            <p role="alert" className="mt-3 text-sm text-danger">
              {error}
            </p>
          )}
          <div className="mt-5 flex justify-between gap-2">
            <Button variant="ghost" onClick={() => setDraft([])} disabled={draft.length === 0}>
              Clear selection
            </Button>
            <div className="flex gap-2">
              <Button onClick={onClose}>Cancel</Button>
              <Button
                variant="primary"
                disabled={saving}
                onClick={async () => {
                  setSaving(true);
                  try {
                    await onSave(draft);
                  } catch {
                    setError("Could not update the scope. Try again.");
                  } finally {
                    setSaving(false);
                  }
                }}
              >
                {saving ? "Saving…" : "Apply"}
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
