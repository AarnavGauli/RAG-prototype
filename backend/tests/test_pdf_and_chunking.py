from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from app.errors import PdfRejected
from app.services import pdf
from app.services.chunking import chunk_page, chunk_pages, estimate_tokens
from app.services.pdf import PageText, normalise_text
from tests.conftest import make_pdf


def write(tmp_path: Path, data: bytes, name: str = "x.pdf") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_extraction_preserves_one_based_page_numbers(tmp_path: Path) -> None:
    pages = pdf.extract_pages(write(tmp_path, make_pdf(["first page text", "second page text", "third page text"])))
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert "second page" in pages[1].text and "first" not in pages[1].text


def test_blank_pages_are_kept_with_empty_text(tmp_path: Path) -> None:
    pages = pdf.extract_pages(write(tmp_path, make_pdf(["one", "two", "three"], blank_pages={1})))
    assert [bool(p.text) for p in pages] == [True, False, True]
    assert chunk_pages(pages, 50, 5)[1].page_number == 3  # chunk numbering skips the blank page, page stays right


def test_unicode_and_whitespace_normalisation() -> None:
    assert normalise_text("Café   au lait\r\n\r\n\r\n\r\nexam-\nple\x00") == "Café au lait\n\nexample"


def test_validate_rejects_non_pdf_malformed_and_encrypted(tmp_path: Path) -> None:
    with pytest.raises(PdfRejected) as e:
        pdf.validate_pdf(write(tmp_path, b"hello world"), 10)
    assert e.value.code == "not_a_pdf"
    with pytest.raises(PdfRejected) as e:
        pdf.validate_pdf(write(tmp_path, b"%PDF-1.7\nthis is not really a pdf"), 10)
    assert e.value.code == "malformed_pdf"
    with pytest.raises(PdfRejected) as e:
        pdf.validate_pdf(write(tmp_path, make_pdf(encrypt=True)), 10)
    assert e.value.code == "encrypted_pdf"
    with pytest.raises(PdfRejected) as e:
        pdf.validate_pdf(write(tmp_path, make_pdf(["a", "b", "c"])), 2)
    assert e.value.code == "too_many_pages"
    assert pdf.validate_pdf(write(tmp_path, make_pdf()), 10) == 3


SENTENCES = " ".join(f"Sentence number {i} describes item {i} in some detail." for i in range(40))


def test_chunks_respect_size_and_offsets_slice_page_text() -> None:
    page = PageText(4, SENTENCES)
    chunks = chunk_page(page, 50, 10)
    assert len(chunks) > 3
    for c in chunks:
        assert c.token_count <= 50
        assert page.text[c.char_start : c.char_end] == c.text
        assert c.page_number == 4


def test_chunks_prefer_sentence_boundaries() -> None:
    chunks = chunk_page(PageText(1, SENTENCES), 50, 10)
    assert all(c.text.rstrip().endswith(".") for c in chunks)
    assert all(c.text[0].isupper() for c in chunks)


def test_overlap_repeats_trailing_text_and_chunks_cover_everything() -> None:
    page = PageText(1, SENTENCES)
    chunks = chunk_page(page, 50, 20)
    assert chunks[1].char_start < chunks[0].char_end  # overlap
    assert chunks[0].char_start == 0 and chunks[-1].char_end == len(page.text)
    no_overlap = chunk_page(page, 50, 0)
    assert all(b.char_start >= a.char_end for a, b in itertools.pairwise(no_overlap))


def test_paragraph_boundaries_are_kept_when_they_fit() -> None:
    text = "First paragraph is short.\n\nSecond paragraph is also short."
    chunks = chunk_page(PageText(1, text), 8, 0)
    assert [c.text for c in chunks] == ["First paragraph is short.", "Second paragraph is also short."]


def test_exceptionally_long_unpunctuated_run_is_split_on_word_boundaries() -> None:
    text = " ".join(f"word{i}" for i in range(1000))
    chunks = chunk_page(PageText(1, text), 60, 10)
    assert len(chunks) >= 1000 // 60
    assert all(c.token_count <= 60 for c in chunks)
    assert all(not c.text.startswith(" ") and not c.text.endswith(" ") for c in chunks)


def test_chunk_indexes_are_sequential_across_pages() -> None:
    chunks = chunk_pages([PageText(1, "alpha beta."), PageText(2, ""), PageText(3, "gamma delta.")], 50, 5)
    assert [(c.page_number, c.chunk_index) for c in chunks] == [(1, 0), (3, 1)]


def test_estimate_tokens_counts_words_and_punctuation() -> None:
    assert estimate_tokens("Hello, world!") == 4
