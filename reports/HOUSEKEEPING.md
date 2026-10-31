# 22-HOUSEKEEPING-LICENSE-ARCTIC

Branch `chore/license-arctic` (from origin/main). Decisions by Patrick, Oct 30 2026.

## 1. What was done

- **License.** Added `LICENSE` (canonical Apache-2.0 text from apache.org, 202 lines, sha256 `cfc7749b…c523d30`) and `NOTICE` ("Preached, Copyright 2026 Patrick Shouse"). `pyproject.toml` has `license = "Apache-2.0"` (PEP 639) and `license-files`. README has a License section saying third-party data is not relicensed: sermon texts and audio keep their own licences (Wesley via CCEL, LibriVox: public domain) per their provenance, and model weights keep theirs.
- **Arctic Embed v1 out of the product, in the eval.** `search/models.toml`: `arctic-embed-l` has `eval_only = true`. `preached.models` adds `ModelSpec.eval_only` and `RUNTIME_MODELS`; a default that is eval-only fails config load. `app/server.py --model` and `search/query.py --model` accept only runtime models; `Searcher(model=...)` raises for eval-only keys. `search/bench.py` still runs it. Arctic was never a documented runtime option elsewhere (README/AGENTS only list it as an allowed-provenance example, left as is).
- **docs/research/embeddings.md.** New "Decisions" section with the line "Excluded from the product by Patrick, Oct 30 2026; kept in the eval for re-runs.", the default staying IBM Granite English R2, and EmbeddingGemma 2 tied once correctly configured and remaining in the eval. Arctic results unchanged; "pending Patrick" wording replaced.

## 2. How to run

```bash
uv lock --check
uv run python -m unittest discover tests
uv run app/server.py --model arctic-embed-l   # exits: eval-only
uv run search/query.py "worry" --model arctic-embed-l   # argparse rejects
```

## 3. Results

- Tests: **562 passed, 0 failed** (was 558; 4 new in `tests/test_search.py`: eval-only flag, Searcher, server, CLI rejection).
- `uv lock --check` passes; `uv build` succeeds with the license metadata.

## 4. Open issues

- No dedicated provenance files exist in the repo; the README points to the sources in Credits and `corpus/catalog.json`. 
- AGENTS.md still lists Arctic Embed among allowed-provenance examples (a provenance statement, not a product option); not edited.

## 5. Dependencies added

None.
