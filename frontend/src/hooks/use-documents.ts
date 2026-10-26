"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { DocumentItem } from "@/lib/types";

const POLL_MS = 1200;

/** Documents list. Polls the backend only while something is queued/processing, so "ready" is always server-confirmed. */
export function useDocuments(enabled: boolean) {
  const [docs, setDocs] = useState<DocumentItem[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("Could not load documents.", "unknown", 0));
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    api
      .listDocuments()
      .then((d) => alive && setDocs(d))
      .catch((e) => alive && setError(e instanceof ApiError ? e : new ApiError("Could not load documents.", "unknown", 0)));
    return () => {
      alive = false;
    };
  }, [enabled]);

  const inFlight = docs?.some((d) => d.status === "queued" || d.status === "processing") ?? false;
  useEffect(() => {
    if (!inFlight) return;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [inFlight, refresh]);

  return { docs, error, refresh };
}
