# Preached

Search a sermon archive and return the preacher's own words. This branch builds the Wesley text corpus, the eval set, and the retrieval benchmark.

```bash
uv run corpus/fetch_wesley.py
uv run corpus/chunk_sermons.py
uv run python eval/validate.py
uv run search/bench.py
uv run search/bench.py --models granite-english-r2 --dedupe
uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
```

Corpus text and the SQLite index stay under `/cache`. Weights use `HF_HOME=/cache/huggingface`. The default embedder is IBM Granite English R2, hybrid RRF. How that was chosen is in `reports/W1-B.md`. Labeling notes are in `eval/README.md`.

The page is a stdlib server. From this worktree:

```bash
uv run app/server.py
```

Then open http://127.0.0.1:8000. Search returns Wesley's published words. Hybrid mode is reciprocal rank fusion with k=60. Adjacent chunks overlap by about 25%, and the API keeps the higher-scoring one so the same words are not listed twice. So `/api/search` does not return the raw top k that `search/query.py` prints: it takes the ranker's top 100 and de-dups down to k (`api_search` in `src/preached/search.py`). `search/bench.py --dedupe` scores that path. For Granite hybrid it gives R@5 0.614, MRR@10 0.497 and nDCG@10 0.546, against 0.629, 0.506 and 0.558 for the raw top 10. Excerpts on the page hide CCEL paragraph numbers. The indexed text is unchanged. Passages with no `start_s` say that audio timing is still coming and link to the CCEL text. Details are in `reports/W2-A.md`. The timestamp hit@k in `reports/W1-CLI.md` is derived from the alignment: equal to the text metric by construction, not an independent audio-accuracy result. Audio accuracy is the W1-C spot-check (median 0.42 s, max 0.76 s against the audio, covered by the 0.75 s pre-roll).

## Credits

- Text: John Wesley, *Sermons on Several Occasions* (public domain), via the [Christian Classics Ethereal Library (CCEL)](https://ccel.org/ccel/wesley/sermons).
- Recordings: [LibriVox](https://librivox.org/) volunteers (public domain), streamed from the [Internet Archive](https://archive.org/).
