# 99-WQ-WHY-THIS-RESULT: each search result says why it is there

Branch `feat/w5-why-this-result` from `origin/main` `8e0017d` (clean tree confirmed before branching and before editing). `origin/main` then advanced to `57ccce4` (#85, `reports/W3-LISTEN-BACKLOG.md` only); it was merged in with no conflicts (no rebase, no force-push), and the full suite was re-run on the merged head.

## 1. What was done

**API.** Every result in `/api/search` (classic and church library) and in both `/api/side` columns now has
`why: {"keyword_rank": int|null, "meaning_rank": int|null, "similarity": float|null, "found_by": "both"|"keyword"|"meaning"}`.

- Where it comes from: `Why` and `Searcher._pack` in `src/preached/search.py`. `bm25`, `dense` and `hybrid` already hold the candidate lists they fused (`_lexical` / `_semantic`, top `CANDIDATES` = 100 in hybrid; the pool of 100 in the single-list modes). `_pack` now takes those same lists and reads each hit's 1-based ranks and dense cosine (rounded to 3 places) off them. No search is re-run and no list is rebuilt.
- Mode rules: `bm25` mode has null meaning fields; `dense` mode has null keyword fields; in hybrid a passage missing from one list has null for that list (and null `similarity` when not in the dense list).
- Privacy: the lists are the ones `_lexical` / `_semantic` return under `searcher._where()` (the visible-only FTS copy and vector matrix on a gated file), exactly as the results. A hidden or unpublished chunk cannot shift a visible rank or similarity.
- `Hit.why` is `field(default=None, compare=False)`: Hit equality is unchanged. `dedupe_adjacent` / `merge_overlapping` keep the kept hit's `why` (its rank does not move, same as its `score`).
- `app/server.py`: `"why"` added to `RESULT_FIELDS` (allow-list kept) and to the `hit_dict` payload. A hit built some other way (no `why`) gets an explicit `"why": null`. `score` unchanged.
- Church: `_church_search` uses `api_search` on the gated church searcher, so church results and the side columns get the same `why` with no extra code.
- No change to `src/preached/abstain.py`.

**Page.** `app/static/app.js` `whyLine(why)` (pure) builds the line; `renderCard` appends it as the card's last element, `<p class="why">`, in muted ink (`app.css`). Wording: "Found by both keyword (#3) and meaning (#1) search · similarity 0.81", "Found by meaning search only (#2) · similarity 0.79", "Found by keyword search only (#4)". Ranks must be positive integers and similarity a finite number, or that part is left out. `index.html` gets a `<details class="levels">` "What the confidence notes mean" under the banners, which explains strong / weak / low / unrated in plain words with no numbers. It works by tap, click or keyboard (no hover-only tooltip), and the summary is a 44px tap target.

**Docs.** `README.md` has a new section, "Reading a search result", after the server paragraph that already describes `/api/search`. It covers `score` (RRF `1/(60+rank)` per list, top 100 each; BM25 score / cosine in the single modes), the `why` fields, and the confidence signals (agreement, `dense_top` against the calibrated floor in `search/abstain.toml`, and the levels). Cites are tree-relative (`src/preached/search.py`, `src/preached/abstain.py`).

**DEPLOY cites (rule 4).** The two new `app/server.py` lines (one at `RESULT_FIELDS`, one in `hit_dict`) move every cite after line 314. I re-pinned all affected `docs/DEPLOY.md` cites (`app/server.py:N` and the `` `:N` `` shorthands that refer to server.py; library.py's `:468`, `:915`, `:962`, `:883-884` and `:921-922` were left alone) and every `CITED` pin in `tests/test_deploy_alerts.py`. `test_every_cited_file_line_holds_its_string` passes, which checks each pin against the file's text. I also spot-read several pins by hand (507, 519, 865, 870-874, 898, 903, 921, 924, 3386). The DEPLOY sentence that named the tree ("the merged tree this file ships in (main plus the listen backlog change)") now reads tree-relative: "The line numbers below are this tree: the tree this file ships in". `docs/DEPLOY.md` is outside the listed file scope, but rule 4 requires this edit.

## 2. How to run it

```bash
PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=$(mktemp -d) HF_HOME=$(mktemp -d) PREACHED_ONNX_DIR=$(mktemp -d) DENO_DIR=$(mktemp -d) XDG_CACHE_HOME=$(mktemp -d) UV_CACHE_DIR=$(mktemp -d) TORCH_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 uv run python -m unittest discover -s tests
# just this feature:
... uv run python -m unittest tests.test_why_this_result tests.test_app_js tests.test_gate_signals
```

## 3. Results

- **Full suite** (temp caches for all seven vars, `PREACHED_REQUIRE_DENO=1`, deno present): `Ran 1121 tests in 246.862s`, **OK (skipped=12)**. The 12 skips are the same 12 as the pre-change run on this branch (1105 tests, skipped=12).
- Before the fixes, the first run on the change had 50 failures, all expected: 48 `test_every_cited_file_line_holds_its_string` subtests (cites moved) and 2 result-key pins (`test_server.RESULT_KEYS`, `test_side.RESULT_KEYS`). Those pins and `test_embed_backend.RESULT_FIELDS` now include `why` on purpose; they were not loosened, they still require the exact key set.
- **New tests**, `tests/test_why_this_result.py` (14):
  - correctness on a hand-built 4-chunk index: hybrid `both` and `meaning`-only with exact ranks and similarities, hybrid `keyword`-only (`candidates=2`), bm25 mode, dense mode, similarity = the cosine rounded to 3 places; `score` still equals the RRF sum;
  - JSON shape: key order, types, and per-mode nulls; the server's BM25 fallback; an explicit `null` for a hit with no `why`;
  - **no extra passes**: one hybrid `App.search` calls `_lexical` twice and `_semantic` twice, the same as before (once for `api_search`, once for `compute_signals`);
  - **privacy**: a gated church file with a hidden chunk that is the ungated dense #1 for "righteousness" gives identical `why` (and `meaning_rank` 1 for the top visible passage) to a file without it. Eight hidden "lantern" sermons that would reorder BM25 (`ORDER_ROWS`) leave the keyword ranks at 1 and 2, identical to the clean file. All 3 queries × 3 modes match;
  - church `/api/search?library=sample` and both `/api/side` columns carry `why`, with exact values for the church hits.
  - Mutation check: I made `_pack` read ranks from the *ungated* lists (`bm25_search(self.connection, …)`, the full matrix). The privacy tests failed (8 subtests), and so did `test_gate_signals.test_search_response_is_identical` (4). I then restored the source from a backup and all tests pass.
- **JS** (`tests/test_app_js.py` `WhyLineTests`, Deno): the three wordings, bad/missing input gives no line, the line is the card's last `<p class="why">`, and the help text names all four levels with no digits.
- **Latency** (informational, unpinned). 20 queries from `eval/questions.jsonl`, in-process `App.search(q, 10, "hybrid")`, against a read-only (`chmod 444`) temp copy of the public-domain `wesley.sqlite` under `mktemp -d`. The query vectors are stored document vectors plus small noise (no encoder; the encoder cost is the same in both trees). Each query takes the median of 7 timed runs, and p50 is over the 20 queries. `origin/main` code came from `git archive` into a temp dir (no checkout), and the runs were interleaved 5 times:

  | run | before p50 ms | after p50 ms |
  | --- | --- | --- |
  | 1 | 64.85 | 68.32 |
  | 2 | 61.75 | 65.04 |
  | 3 | 64.99 | 60.99 |
  | 4 | 64.48 | 63.32 |
  | 5 | 61.16 | 61.56 |
  | median | **64.48** | **63.32** |

  The difference is within noise, as expected: the change adds a dict lookup per packed hit. The temp copy was removed afterwards (path resolved and asserted under `tempfile.gettempdir()` first).
- **Response parity pins.** No test or file in this repo pins an HTTP / in-process / no-church response hash (`grep -rn "61da3646\|cb0fb974\|1d128a7f"` over the tree finds nothing), so no in-repo pin changed. Any gate hash over an `/api/search` or `/api/side` body that has results **will change**, by design, because every result now has a `why` key. I could not recompute the host gate's values because its hashing method and inputs are not in the repo, and I did not guess them. CoS should re-baseline them from this head. No-church parity is unchanged structurally: classic responses with and without a church file are still equal (`test_side` and `test_gate_signals` pass).
- **/cache snapshot** (`find /cache -printf '%p %s %T@'`, 132732 entries before and after). No paths were added or removed and no sizes changed. Three mtimes changed, all at 21:20:03 EDT: `/cache/index/wesley.sqlite-shm`, and `/cache/xdg/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db-shm` / `-wal`. These were not my writes: `/cache/index` is a read-only mount in this sandbox (`touch` gives "Read-only file system"), every one of my runs had `XDG_CACHE_HOME` set to a temp dir (none of them has a `Microsoft/` folder), and the same pair of files had already changed together at 20:37, before this session started. A host-side reader is the likely cause, but I cannot prove it. The only real-cache read was `cp /cache/index/wesley.sqlite` into the temp dir for the latency run. The sandbox's `UV_PYTHON_INSTALL_DIR=/cache/uv-python` (the interpreter) was used as is.

## 4. Open issues, risks, exclusions

- `similarity` is the stored-vector dot product. It is a cosine only because the product's vectors are L2-normalized; fixture vectors that are not normalized show the raw dot product.
- A keyword-only hit in hybrid shows no similarity, even though its cosine could be computed. That was left out on purpose: it would be a value from outside the fused lists.
- The page shows similarity to 2 places, from the API's 3.

## 5. Dependencies

None added.

## R-POST74: merge of post-#74 main

`origin/main` at `e4345392019f16ee22226925a247cb145456e6cf` (#74, 28 commits ahead of this branch at `e14bcd8`) was merged with a normal `git merge` in commit `42014ca`. No rebase, no force-push.

**Conflicts.** None. Git merged every file cleanly. Both sides changed `README.md`, `src/preached/search.py`, `docs/DEPLOY.md`, `tests/test_app_js.py`, `tests/test_deploy_alerts.py`, `tests/test_embed_backend.py`, `tests/test_server.py` and `tests/test_side.py`, but in hunks that do not overlap. I read each merged file to check that both sides are kept:
- `README.md`: main's quickstart rewrite (`$PREACHED_CACHE` paths, export steps, `SLUG`) is all there, and this branch's "Reading a search result" section still follows the `--library SLUG` paragraph.
- `src/preached/search.py`: main's `_VERSE_REF` / `PARAGRAPH_NUMBER` change (around line 700) sits next to this branch's `Why` dataclass, `Hit.why` and `_pack` lists. They do not interact: `why` is built from rowids and ranks, not from excerpt text.
- `docs/DEPLOY.md`: main's temp-dir suite command and `copy_index` paragraph are kept, along with this branch's re-pinned cites.
- the four test files: main's `cache_guard` arming line is kept, along with this branch's additions.

No `--ours`/`--theirs` or whole-file picks were used.

**Semantic fix after the merge.** Main (#84) added `test_cache_guard.test_every_test_module_imports_the_guard`. This branch's new `tests/test_why_this_result.py` did not import the guard, so the first post-merge suite run had 1 failure. I added the same arming line the other modules use (`__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()`) after `from __future__ import annotations`.

**DEPLOY cites (rule 4).** Re-pinned: none, old to new: none. The merge changed none of the cited files (`git diff 57ccce4 origin/main -- app/ src/preached/library.py src/preached/youtube/` is empty), and the post-merge diff of those files against `e14bcd8` is empty. I read every `app/server.py`, `src/preached/library.py`, `src/preached/youtube/library.py` and `src/preached/youtube/pipeline.py` cite in `docs/DEPLOY.md` on the merged tree, one line per cite, and each still holds its string. The tree sentence is already tree-relative ("The line numbers below are this tree"). `test_every_cited_file_line_holds_its_string` passes.

**Parity refs.** Unchanged, and nothing is re-baselined (CTO ruling). I expect the `why` field to move every gate parity ref that hashes an `/api/search` or `/api/side` body with at least one result: the HTTP, in-process and no-church response hashes. Empty-result bodies, `/healthz` and static-file refs should not move. Main's `PARAGRAPH_NUMBER` change also changes some displayed excerpts on its own, so CTO's two hash sets separate the two causes.

**Suite** (merged tree plus the guard fix; `PREACHED_REQUIRE_DENO=1 HF_HUB_OFFLINE=1`, with `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR` and `TORCH_HOME` each a fresh `mktemp -d`):

```
Ran 1136 tests in 254.188s

OK (skipped=12)
```

Before the guard fix: `Ran 1136 tests in 248.874s` / `FAILED (failures=1, skipped=12)`. The one failure was `test_every_test_module_imports_the_guard` (`['test_why_this_result.py']`).

**/cache diff.** I took a listing of `/cache` (`find -printf '%p %s %T@'`, 132,732 entries) before the first run and after the second. Entry count and sizes are identical. Three mtimes changed, all under `/cache/xdg`:
- `/cache/xdg` (directory) 21:05:34 to 22:04:39.
- `/cache/xdg/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db-shm` and `onnxruntime.db-wal`, 21:57:10 to 22:06:46. Sizes are unchanged.

None of these is project data (index, corpus, models). The `.onnxruntime` WAL is onnxruntime's own telemetry DB. It was already being written at 21:57:10, before my first snapshot and before I ran anything. It was written again at 22:09:58, when only `sleep` was running here. So something outside my runs also writes it. All seven test cache dirs were temp. My temp `XDG_CACHE_HOME` stayed empty, and no process in my namespace other than the agent shell had `XDG_CACHE_HOME=/cache/xdg`.

One exception: I ran a single `uv run python -c 'import onnxruntime'` lookup (not a test) in a shell that had not sourced the temp env. That probably caused the 22:07:39 WAL write. The `/cache/xdg` directory mtime at 22:04:39 fell during my suite, and I cannot attribute it. Every entry left in `/cache/xdg` has an older mtime, so an entry was created and then removed there.

## PR BODY

Each search result now says why it is listed. Every `/api/search` and `/api/side` result gets a `why` object: `keyword_rank` and `meaning_rank` (1-based places in the gated BM25 and dense top-100 lists the ranker fused), `similarity` (dense cosine, 3 places) and `found_by`. They are read off the lists the search already ran, so there is no extra pass (p50 64.48 → 63.32 ms, noise), and through the publish gate, so a hidden chunk never moves a visible rank (tested, including a mutation check). `score` is unchanged. The page shows one muted line per card ("Found by both keyword (#3) and meaning (#1) search · similarity 0.81") and a details block that explains the strong / weak / low / unrated levels. README: "Reading a search result". DEPLOY.md cites and `CITED` pins are re-pinned for the two new `app/server.py` lines. Gate response-hash pins over result bodies will change (not pinned in the repo; see the report). Merged with post-#74 main (no conflicts; see R-POST74). Full suite: Ran 1136, OK (skipped=12), `PREACHED_REQUIRE_DENO=1`, temp caches.

Example (`hybrid`, read-only temp copy of the Wesley index, fields trimmed; the query vector here is a stored document vector, so similarity 1.0 at #1 is expected):

```json
{
  "mode": "hybrid",
  "results": [
    {"chunk_id": "wesley-005-c0037", "sermon_title": "Justification By Faith",
     "score": 0.03278688524590164,
     "why": {"keyword_rank": 1, "meaning_rank": 1, "similarity": 1.0, "found_by": "both"}},
    {"chunk_id": "wesley-134-c0017", "sermon_title": "True Christianity Defended",
     "score": 0.025693893735130847,
     "why": {"keyword_rank": 37, "meaning_rank": 5, "similarity": 0.911, "found_by": "both"}}
  ]
}
```

(`0.0328 = 1/61 + 1/61`; `0.0257 = 1/97 + 1/65`.)

`git diff --stat origin/main...HEAD`:

```
 README.md                     |   8 ++
 app/server.py                 |   2 +
 app/static/app.css            |  42 ++++++-
 app/static/app.js             |  30 +++++
 app/static/index.html         |  14 +++
 docs/DEPLOY.md                | 112 ++++++++---------
 reports/W5-WHY-THIS-RESULT.md | 111 +++++++++++++++++
 src/preached/search.py        |  68 ++++++++++-
 tests/test_app_js.py          |  57 +++++++++
 tests/test_deploy_alerts.py   |  86 ++++++-------
 tests/test_embed_backend.py   |   1 +
 tests/test_server.py          |   1 +
 tests/test_side.py            |   1 +
 tests/test_why_this_result.py | 276 ++++++++++++++++++++++++++++++++++++++++++
 14 files changed, 702 insertions(+), 107 deletions(-)
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)
