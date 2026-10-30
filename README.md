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

The page is a stdlib server. From this worktree:

```bash
uv run app/server.py
```

Then open http://127.0.0.1:8000. Search returns Wesley's published words. Hybrid mode is reciprocal rank fusion with k=60. Adjacent chunks overlap by about 25%, and the API keeps the higher-scoring one so the same words are not listed twice. Passages with no `start_s` say that audio timing is still coming and link to the CCEL text. Details are in `reports/W2-A.md`.
