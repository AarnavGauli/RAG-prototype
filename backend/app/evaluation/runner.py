"""RAG evaluation: deterministic retrieval/citation/abstention metrics, with LLM-judged metrics kept separate.

Everything runs in an isolated temporary workspace (own SQLite file, own FAISS index); it never touches user data.
The default ``offline`` generator is a deterministic extractive stand-in. It exercises the pipeline wiring
(prompt assembly, structured-output validation, citation validation, abstention) but says nothing about the
quality of a real language model. ``live`` uses the configured LLM provider and is opt-in because it costs money.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.config import Settings
from app.context import AppContext, build_context
from app.db import Base, session_scope
from app.models import Chunk, Conversation, Document
from app.providers.base import EmbeddingProvider, LLMMessage, LLMProvider
from app.services import answering, indexing
from app.services.retrieval import authorised_documents, retrieve

DATA = Path(__file__).parent / "data"
OWNER = "eval-owner"
_STOP = set(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "do",
        "does",
        "did",
        "how",
        "what",
        "when",
        "who",
        "which",
        "where",
        "why",
        "many",
        "much",
        "up",
        "by",
        "with",
        "from",
        "as",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "has",
        "have",
        "had",
        "can",
        "will",
        "would",
        "should",
        "there",
        "their",
        "they",
        "them",
        "you",
        "your",
    ]
)
_WORD = re.compile(r"[\w$%.,:-]+", re.UNICODE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word.removesuffix("e")


def _content_words(text: str) -> set[str]:
    words = {w.strip(".,:-").lower() for w in _WORD.findall(text)} - _STOP - {""}
    return {_stem(w) for w in words}


class OfflineExtractiveLLM(LLMProvider):
    """Deterministic test double: answers with the best-overlapping sentence from the supplied sources."""

    name = "offline-extractive"
    model = "offline-extractive-v1"

    def generate_structured(
        self, *, system: str, messages: list[LLMMessage], schema: dict, max_tokens: int
    ) -> dict[str, Any]:
        text = messages[-1].content
        question = text.rsplit("Question:", 1)[-1].strip()
        q_words = _content_words(question)
        unique: dict[str, str] = {}  # overlapping chunks repeat sentences; count each once
        for label, body in re.findall(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', text, re.DOTALL):
            for sentence in re.split(r"(?<=[.!?])\s+", body):
                unique.setdefault(" ".join(sentence.split()), label)
        sentences = [(label, sentence) for sentence, label in unique.items()]
        words = [_content_words(sentence) for _, sentence in sentences]
        # weight shared words by rarity across the supplied sentences (a tiny IDF), so "bike-share" matters less than "stations"
        df = {w: sum(1 for ws in words if w in ws) for w in q_words}
        best: tuple[float, str, str] = (0.0, "", "")
        for (label, sentence), ws in zip(sentences, words, strict=True):
            shared = q_words & ws
            score = sum(1 / df[w] for w in shared)
            if len(shared) >= 2 and score > best[0]:
                best = (score, label, sentence)
        if not best[1]:
            return {
                "sufficient_evidence": False,
                "answer": "The sources do not contain this information.",
                "citations": [],
            }
        _, label, sentence = best
        return {
            "sufficient_evidence": True,
            "answer": f"{sentence} [{label}]",
            "citations": [{"source": label, "quote": sentence}],
        }


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"faithful": {"type": "boolean"}, "relevant": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["faithful", "relevant"],
}


def _evidence_match(chunk_text: str, chunk_page: int, ev: dict[str, Any]) -> bool:
    return chunk_page == ev["page"] and _norm(ev["phrase"]) in _norm(chunk_text)


def _ingest(ctx: AppContext, pdf_path: Path) -> str:
    assert ctx.settings.upload_dir is not None
    stored = "eval-sample.pdf"
    shutil.copy(pdf_path, ctx.settings.upload_dir / stored)
    with session_scope(ctx.session_factory) as s:
        doc = Document(
            owner_id=OWNER, name=pdf_path.name, stored_name=stored, size_bytes=pdf_path.stat().st_size, sha256="eval"
        )
        s.add(doc)
        s.flush()
        doc_id = doc.id
    indexing.process_document(ctx, doc_id)
    with session_scope(ctx.session_factory) as s:
        doc = s.get(Document, doc_id)
        if doc is None or doc.status != "ready":
            raise RuntimeError(f"Evaluation document failed to index: {doc.error_message if doc else 'missing'}")
    return doc_id


def run_evaluation(
    *,
    embedder: EmbeddingProvider,
    llm: LLMProvider | None = None,
    generator: str = "offline",
    judge: bool = False,
    ks: tuple[int, ...] = (1, 3, 5),
    chunk_size: int = 80,
    chunk_overlap: int = 15,
    min_score: float | None = None,
    dataset_path: Path | None = None,
    pdf_path: Path | None = None,
    base_settings: Settings | None = None,
) -> dict[str, Any]:
    dataset = json.loads((dataset_path or DATA / "dataset.json").read_text())
    pdf_path = pdf_path or DATA / dataset["document"]
    if generator == "live" and llm is None:
        raise ValueError("generator='live' requires an LLM provider")
    if judge and generator != "live":
        raise ValueError("LLM-judged metrics require generator='live'")

    tmp = Path(tempfile.mkdtemp(prefix="pdfi-eval-"))
    try:
        overrides: dict[str, Any] = {
            "data_dir": tmp,
            "chunk_size_tokens": chunk_size,
            "chunk_overlap_tokens": chunk_overlap,
            "retrieval_top_k": max(ks),
            "retrieval_max_top_k": max(max(ks), 20),
        }
        if base_settings is not None:
            overrides["embedding_provider"] = base_settings.embedding_provider
            overrides["retrieval_min_score"] = base_settings.retrieval_min_score
        if min_score is not None:
            overrides["retrieval_min_score"] = min_score
        settings = Settings(**overrides)
        gen: LLMProvider = OfflineExtractiveLLM() if generator == "offline" else llm  # type: ignore[assignment]
        ctx = build_context(settings, embedder=embedder, llm=gen)
        Base.metadata.create_all(ctx.engine)
        try:
            _ingest(ctx, pdf_path)
            return _evaluate(ctx, dataset, ks, generator, judge, llm)
        finally:
            ctx.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _evaluate(
    ctx: AppContext, dataset: dict, ks: tuple[int, ...], generator: str, judge: bool, judge_llm: LLMProvider | None
) -> dict[str, Any]:
    per_q: list[dict[str, Any]] = []
    with session_scope(ctx.session_factory) as s:
        docs = authorised_documents(s, OWNER)
        n_chunks = s.scalar(select(func.count()).select_from(Chunk)) or 0
        for q in dataset["questions"]:
            ranked = retrieve(ctx, s, query=q["question"], documents=docs, top_k=max(ks), min_score=-1.0).chunks
            evidence = q["expected_evidence"]
            rank = None
            for i, c in enumerate(ranked, start=1):
                if any(_evidence_match(c.text, c.page_number, ev) for ev in evidence):
                    rank = i
                    break
            conv = Conversation(owner_id=OWNER, title=q["id"])
            s.add(conv)
            s.flush()
            entry: dict[str, Any] = {
                "id": q["id"],
                "type": q["type"],
                "question": q["question"],
                "evidence_rank": rank,
                "top_retrieved_pages": [c.page_number for c in ranked[:3]],
                "top_score": round(ranked[0].score, 4) if ranked else None,
            }
            try:
                _, assistant = answering.ask(ctx, s, OWNER, conv, q["question"])
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"
                per_q.append(entry)
                continue
            abstained = assistant.status == "insufficient_evidence"
            entry.update(abstained=abstained, answer=assistant.content, citations=[])
            valid = True
            for cit in assistant.citations:
                chunk = s.scalar(select(Chunk).where(Chunk.source_id == cit.chunk_source_id))
                ok = chunk is not None and chunk.page_number == cit.page_number and chunk.document_id == cit.document_id
                if ok and chunk is not None:
                    ok = _norm(cit.excerpt.strip("…")) in _norm(chunk.text)
                valid &= bool(ok)
                matches = bool(chunk) and any(_evidence_match(chunk.text, chunk.page_number, ev) for ev in evidence)
                entry["citations"].append(
                    {
                        "label": cit.label,
                        "page": cit.page_number,
                        "valid": bool(ok),
                        "supports_expected_evidence": matches,
                        "quote_verified": cit.quote_verified,
                    }
                )
            entry["citations_valid"] = valid
            alts = q.get("expected_answer_contains") or []
            if alts and not abstained:
                entry["answer_contains_expected"] = any(_norm(a) in _norm(assistant.content) for a in alts)
            if not abstained and assistant.citations:
                cited_text = " ".join(
                    s.scalar(select(Chunk.text).where(Chunk.source_id == c.chunk_source_id)) or ""
                    for c in assistant.citations
                )
                words = _content_words(re.sub(r"\[S\d+\]", "", assistant.content))
                entry["lexical_groundedness"] = (
                    round(len(words & _content_words(cited_text)) / len(words), 3) if words else None
                )
            if judge and judge_llm is not None and not abstained:
                entry["llm_judge"] = _judge(
                    judge_llm, q["question"], assistant.content, [c.excerpt for c in assistant.citations]
                )
            per_q.append(entry)
        s.rollback()  # evaluation conversations are throwaway

    return _summarise(ctx, dataset, per_q, ks, generator, judge, n_chunks)


def _judge(llm: LLMProvider, question: str, answer: str, excerpts: list[str]) -> dict[str, Any]:
    prompt = (
        "You are grading a RAG answer. Evidence excerpts:\n"
        + "\n---\n".join(excerpts)
        + f"\n\nQuestion: {question}\nAnswer: {answer}\n\nIs every claim in the answer supported by the excerpts (faithful), "
        "and does it address the question (relevant)?"
    )
    try:
        out = llm.generate_structured(
            system="You are a strict evaluator.",
            messages=[LLMMessage("user", prompt)],
            schema=JUDGE_SCHEMA,
            max_tokens=300,
        )
        return {
            "faithful": bool(out.get("faithful")),
            "relevant": bool(out.get("relevant")),
            "reason": str(out.get("reason", ""))[:300],
        }
    except Exception as exc:
        return {"error": type(exc).__name__}


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _summarise(
    ctx: AppContext,
    dataset: dict,
    per_q: list[dict[str, Any]],
    ks: tuple[int, ...],
    generator: str,
    judge: bool,
    n_chunks: int,
) -> dict[str, Any]:
    ans_q = [q for q in per_q if q["type"] == "answerable"]
    unans = [q for q in per_q if q["type"] == "unanswerable"]
    answered = [q for q in per_q if "abstained" in q]
    judged = [q for q in per_q if isinstance(q.get("llm_judge"), dict) and "error" not in q["llm_judge"]]
    ranks = [q["evidence_rank"] for q in ans_q]
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "embedding_model": ctx.embedder.model_id,
            "chunk_size_tokens": ctx.settings.chunk_size_tokens,
            "chunk_overlap_tokens": ctx.settings.chunk_overlap_tokens,
            "min_score": ctx.settings.min_score,
            "generator": generator,
            "generator_model": ctx.llm.model,
            "chunks_indexed": n_chunks,
            "questions": len(per_q),
        },
        "deterministic": {
            "retrieval": {
                "hit_at_k": {str(k): _rate(sum(1 for r in ranks if r is not None and r <= k), len(ans_q)) for k in ks},
                "mrr": round(sum(1 / r for r in ranks if r) / len(ans_q), 3) if ans_q else None,
                "answerable_questions": len(ans_q),
            },
            "abstention": {
                "correct_abstain_rate_on_unanswerable": _rate(sum(1 for q in unans if q.get("abstained")), len(unans)),
                "false_abstain_rate_on_answerable": _rate(sum(1 for q in ans_q if q.get("abstained")), len(ans_q)),
            },
            "citations": {
                "validity_rate": _rate(
                    sum(1 for q in answered if q.get("citations") and q["citations_valid"]),
                    sum(1 for q in answered if q.get("citations")),
                ),
                "supports_expected_evidence_rate": _rate(
                    sum(1 for q in ans_q if any(c["supports_expected_evidence"] for c in q.get("citations", []))),
                    sum(1 for q in ans_q if not q.get("abstained") and "error" not in q),
                ),
            },
            "answers": {
                "contains_expected_rate": _rate(
                    sum(1 for q in ans_q if q.get("answer_contains_expected")),
                    sum(1 for q in ans_q if "answer_contains_expected" in q),
                ),
                "mean_lexical_groundedness": round(
                    sum(q["lexical_groundedness"] for q in per_q if q.get("lexical_groundedness") is not None)
                    / max(1, sum(1 for q in per_q if q.get("lexical_groundedness") is not None)),
                    3,
                ),
            },
        },
        "llm_judged": (
            {
                "disclaimer": "Scores come from a language model and are not objective ground truth.",
                "faithful_rate": _rate(sum(1 for q in judged if q["llm_judge"]["faithful"]), len(judged)),
                "relevant_rate": _rate(sum(1 for q in judged if q["llm_judge"]["relevant"]), len(judged)),
                "judged_answers": len(judged),
            }
            if judge
            else None
        ),
        "notes": [
            "Deterministic metrics use exact page/phrase matching against expected_evidence.",
            "Hit@k is computed from the raw vector ranking, ignoring the relevance threshold.",
            "Abstention combines the relevance threshold with the generator's own sufficiency judgement.",
            "lexical_groundedness is a crude word-overlap heuristic, not a faithfulness proof.",
        ]
        + (
            [
                "The offline generator is a deterministic extractive stand-in; answer metrics validate pipeline wiring, not LLM quality."
            ]
            if generator == "offline"
            else []
        ),
        "per_question": per_q,
    }
    return report
