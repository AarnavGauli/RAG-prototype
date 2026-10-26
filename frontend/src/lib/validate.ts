import { formatBytes } from "./format";

export interface FileCheck {
  ok: boolean;
  error?: string;
}

/** Client-side pre-check for fast feedback. The server repeats (and is the authority for) every check. */
export function validateFile(file: File, maxMb: number): FileCheck {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return { ok: false, error: `"${file.name}" is not a PDF. Only .pdf files are supported.` };
  if (file.size === 0) return { ok: false, error: `"${file.name}" is empty.` };
  if (file.size > maxMb * 1024 * 1024)
    return { ok: false, error: `"${file.name}" is ${formatBytes(file.size)}; the limit is ${maxMb} MB.` };
  return { ok: true };
}
