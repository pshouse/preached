# Preached

Search a sermon archive and return the preacher's own words. This branch builds the Wesley text corpus, the eval set, and the retrieval benchmark.

```bash
uv run corpus/fetch_wesley.py
uv run corpus/chunk_sermons.py
uv run python eval/validate.py
uv run search/bench.py
uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
```

Corpus text and the SQLite index stay under `/cache`. Weights use `HF_HOME=/cache/huggingface`. The default embedder is IBM Granite English R2, hybrid RRF. How that was chosen is in `reports/W1-B.md`. Labeling notes are in `eval/README.md`.
