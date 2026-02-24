# CalibreGPT Enhancement Plan

## Phase 1: Safety and Test Coverage
- Add deterministic unit tests for chunking, update detection, and DB/index migration logic.
- Add integration tests for CLI commands with mocked OpenAI API calls.
- Add migration regression tests to protect multi-model indexing behavior.

## Phase 2: Multi-Model Embedding Migration
- Keep `text-embedding-ada-002` as the live baseline index.
- Add resumable migration to an alternate embedding model (default target: `text-embedding-3-small`).
- Store alternate-model vectors in `chunk_embeddings` and write to a model-specific FAISS index file.
- Track migration progress (`processed`, `remaining`) and run repeatedly until complete.
- Switch query traffic to the new model only after ranking parity checks.

## Phase 3: External RAG Interfaces
- Extract a reusable core library for indexing/retrieval/generation.
- Keep Calibre plugin as an adapter over the shared core.
- Add CLI/API endpoints for use in ChatGPT and other engines.

## Phase 4: Unindexable File Conversion (New)
- Build a preprocessing pipeline for files not currently indexable by Calibre full-text.
- Route by file type:
- Text-rich formats: extraction-first strategy (PDF/text/office parsers).
- Image/scanned formats: OCR strategy with page-level confidence thresholds.
- Persist extracted/OCR text into a staging store before chunking/embedding.
- Add tests for file routing, extraction/OCR fallback, and failure handling.

## Phase 5: Operational Hardening
- Add resumable batch jobs and checkpoints for long-running embedding migrations.
- Add observability (progress logs and error counters).
- Add rollback and dual-index validation procedures before cutover.
