"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "./button";

interface Props {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ open, title, description, confirmLabel, busy, onConfirm, onCancel }: Props) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && !busy && onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-surface p-5 shadow-xl">
          <Dialog.Title className="font-serif text-lg font-semibold">{title}</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-muted">{description}</Dialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <Button onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" onClick={onConfirm} disabled={busy}>
              {busy ? "Deleting…" : confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
