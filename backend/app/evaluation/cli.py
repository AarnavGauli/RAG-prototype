"""CLI: python -m app.evaluation.cli [--embedding hash|configured] [--live] [--judge] [--output report.json]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import Settings
from app.evaluation.runner import run_evaluation
from app.providers.embeddings import HashEmbedding, build_embedding_provider
from app.providers.llm import build_llm_provider


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the PDF Intelligence RAG evaluation suite.")
    p.add_argument(
        "--embedding",
        choices=["hash", "configured"],
        default="hash",
        help="'hash' is offline and reproducible (default); 'configured' uses PDFI_EMBEDDING_* settings",
    )
    p.add_argument("--live", action="store_true", help="Use the configured LLM provider (costs money; opt-in)")
    p.add_argument("--judge", action="store_true", help="Add LLM-judged metrics (requires --live)")
    p.add_argument("--chunk-size", type=int, default=80)
    p.add_argument("--chunk-overlap", type=int, default=15)
    p.add_argument("--min-score", type=float, default=None, help="Override the relevance threshold")
    p.add_argument("--output", type=Path, default=None, help="Write the JSON report here (default: stdout)")
    args = p.parse_args(argv)

    settings = Settings()
    if args.embedding == "hash":
        settings = Settings(embedding_provider="hash")
        embedder = HashEmbedding()
    else:
        embedder = build_embedding_provider(settings)
    llm = build_llm_provider(settings) if args.live else None
    if llm is not None:
        llm.check_ready()
    report = run_evaluation(
        embedder=embedder,
        llm=llm,
        generator="live" if args.live else "offline",
        judge=args.judge,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        min_score=args.min_score,
        base_settings=settings,
    )
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text)
        det = report["deterministic"]
        print(f"Report written to {args.output}")
        print(
            json.dumps(
                {
                    "config": report["config"],
                    "retrieval": det["retrieval"],
                    "abstention": det["abstention"],
                    "citations": det["citations"],
                },
                indent=2,
            )
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
