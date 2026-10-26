import type { ReactNode } from "react";
import { AlertTriangle, Info, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";

const tones = {
  info: { box: "bg-accent-soft text-ink border-accent/30", icon: Info },
  warn: { box: "bg-warn-soft text-ink border-warn/40", icon: AlertTriangle },
  error: { box: "bg-danger-soft text-ink border-danger/40", icon: XCircle },
} as const;

export function Notice({
  tone,
  title,
  children,
  action,
  className,
}: {
  tone: keyof typeof tones;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const Icon = tones[tone].icon;
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cn("flex gap-3 rounded-lg border p-3 text-sm", tones[tone].box, className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        {children && <div className="mt-0.5 break-words text-muted">{children}</div>}
        {action && <div className="mt-2">{action}</div>}
      </div>
    </div>
  );
}
