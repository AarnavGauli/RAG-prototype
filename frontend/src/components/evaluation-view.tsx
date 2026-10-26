"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { api, ApiError, describeError } from "@/lib/api";
import { percent } from "@/lib/format";
import type { EvalReport } from "@/lib/types";

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 font-serif text-3xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function EvaluationView() {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let alive = true;
    api
      .latestEvaluation()
      .then((r) => alive && setReport(r))
      .catch((e) => alive && !(e instanceof ApiError && e.code === "no_report") && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setReport(await api.runEvaluation());
    } catch (e) {
      setError(e);
    } finally {
      setRunning(false);
    }
  }

  const det = report?.deterministic;
  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <Link href="/" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Back to documents
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-serif text-3xl font-semibold">RAG evaluation</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Deterministic retrieval, citation and abstention checks over a bundled sample document. It runs in an isolated
            workspace and never touches your uploads.
          </p>
        </div>
        <Button variant="primary" onClick={() => void run()} disabled={running}>
          {running ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
          {running ? "Running…" : "Run evaluation"}
        </Button>
      </div>

      {Boolean(error) && (
        <Notice tone="error" title={describeError(error).title} className="mt-4">
          {describeError(error).message}
        </Notice>
      )}
      {loading && <div className="skeleton mt-6 h-32 w-full" aria-label="Loading report" />}
      {!loading && !report && !error && (
        <p className="mt-8 rounded-xl border border-dashed border-line p-8 text-center text-sm text-muted">
          No report yet. Run the evaluation to generate one (the first run may download the embedding model).
        </p>
      )}

      {report && det && (
        <div className="mt-6 space-y-6">
          <Notice tone="info" title={`Generator: ${report.config.generator}`}>
            {report.notes.join(" ")}
          </Notice>
          <section aria-label="Metrics" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(det.retrieval.hit_at_k).map(([k, v]) => (
              <Metric key={k} label={`Hit rate @${k}`} value={percent(v)} hint="expected evidence among top-k chunks" />
            ))}
            <Metric label="MRR" value={det.retrieval.mrr?.toFixed(2) ?? "n/a"} hint="mean reciprocal rank of first hit" />
            <Metric label="Correct abstention" value={percent(det.abstention.correct_abstain_rate_on_unanswerable)} hint="unanswerable questions refused" />
            <Metric label="False abstention" value={percent(det.abstention.false_abstain_rate_on_answerable)} hint="answerable questions refused" />
            <Metric label="Citation validity" value={percent(det.citations.validity_rate)} hint="citations resolving to real chunks/pages" />
          </section>
          <p className="text-xs text-muted">
            Embedding model: {String(report.config.embedding_model)} · chunk size {String(report.config.chunk_size_tokens)} tokens · threshold{" "}
            {String(report.config.min_score)} · generated {new Date(report.generated_at).toLocaleString()}
          </p>
          <section aria-label="Per-question results" className="overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="p-3">Question</th>
                  <th className="p-3">Type</th>
                  <th className="p-3">Evidence rank</th>
                  <th className="p-3">Top score</th>
                  <th className="p-3">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {report.per_question.map((q) => (
                  <tr key={q.id} className="border-b border-line last:border-0">
                    <td className="p-3">{q.question}</td>
                    <td className="p-3 text-muted">{q.type}</td>
                    <td className="p-3">{q.evidence_rank ?? "—"}</td>
                    <td className="p-3">{q.top_score?.toFixed(3) ?? "—"}</td>
                    <td className="p-3">{q.error ? `error: ${q.error}` : q.abstained ? "abstained" : "answered"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}
