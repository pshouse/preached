# W4-SUBMIT-NITS: CTO #52 should-fixes on the demo script and submission draft

Branch `docs/w4-submit-nits` from `origin/main` (`47da348`). Docs only: `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md`, this report. No code, test, dependency, eval or index change. Nothing deployed or submitted. Merge commits only; this branch was not rebased.

## Changes (old -> new, evidence)

### S1. Tailnet sentence (`docs/DEMO-SCRIPT.md` pre-flight)

Old: "No tailnet was running on the machine used to write this draft."

New: "A tailnet-only demo exists; the public URL is Patrick's decision."

No URL was added. The placeholder is unchanged: `http://<this machine's tailnet name>:PORT` and `fill in: ______`.

### S2. "0 skipped" names every skip source; headline is robust

Old claims row: "971 tests pass on `main` (`bbdb1ba`), 0 skipped on a machine that has the `/cache` ONNX artifacts; some tests skip without them."

New: headline "over 970 tests". Exact figure stays in the claims table: 987 pass, 0 skipped, on `main` (`47da348`), and only when every skip source below is present. The status line now pins `47da348` and points at that headline; it says live demo queries were last re-checked at `bbdb1ba` (not re-run here). PR #51 is still open ("W3-OBS-GAPS: log reload BM25 fallbacks + clean stop; #48 SF1/SF2 tests") and will change the count, which is why the headline is not the exact number.

Skip lines checked on `47da348` (the lines named in the review had not moved). Extra sites on this main are included so the 0-skipped condition is complete:

| Source | Where it skips | What this tree had |
| --- | --- | --- |
| `/cache` ONNX artifacts | `tests/test_embed_backend.py:657`, `:707`, `:714`, `:739`, `:1076`, `:1143` (`skipTest`, "granite onnx artifacts are not in /cache") | `model.fp32.onnx` present under the pinned revision |
| deno | `tests/test_app_js.py:439`, `:618`; `tests/test_privacy_wire_fix.py:246`; also `tests/test_mobile_ux.py:239` (class skip, landed with #53) and `tests/test_privacy_merge.py:217` (`skipTest` inside `run_page`) | deno 2.9.8 on PATH |
| `/cache/asr-repro` clips | `tests/test_coverage.py:291` | `/cache/asr-repro/c01.wav` present |
| index + model | `tests/test_shutdown.py:173` (`/cache/index/wesley.sqlite` and the pinned ONNX directory) | both present |
| chunked corpus | `tests/test_eval_leak.py:169` (`/cache/corpus/wesley/chunks.jsonl`, via `PREACHED_CACHE`) | file present |
| writable model mount | `tests/test_embed_backend.py:718` (skips even when the ONNX file exists, if the parent of the ONNX root is not writable) | writable here |

Command: `uv run python -m unittest discover -s tests`

Result on `47da348`: `Ran 987 tests in 242.526s`, then `OK`. No `(skipped=N)` line. Exit 0. So this machine skipped 0.

### S3. Full-server memory cites `:55` and `:73`, not mixed `:31`

Checked `reports/W4-DEMO-PREP.md` (77 lines). The numbers are there, split across the two lines, so both are cited:

- Line 55 holds "measured 722.7 MiB at start / about 728 MiB after queries on `efdf8ab`". It does not hold the 969 peak.
- Line 73 holds "peak VmHWM about 969 MiB during model load". It does not hold 722.7 or 728.
- Line 31 is the old mix: embedder RSS 683 MiB together with "peak (VmHWM) about 969 MiB". It is not cited.

Old draft: "722.7 MiB at start / about 728 MiB after queries / peak about 969 MiB ... quoted in `reports/W4-DEMO-PREP.md`".

New draft: 722.7 / about 728 cited at `reports/W4-DEMO-PREP.md:55`; peak about 969 cited at `reports/W4-DEMO-PREP.md:73`. Still "CTO review of `efdf8ab`, not re-measured by an agent".

Old demo-script backing: "722.7 MiB at start, peak about 969 MiB, CTO review in `reports/W4-DEMO-PREP.md`".

New: same figures, plus "about 728 MiB after queries" (that number is on line 55 and was already in the draft), cited at `:55` and `:73`.

### S4. "approved passages" -> published-gate wording

README.md line 37 (verified): a sermon appears "only when it is approved (`--ack-review`), its import status is `ok`, and its ASR coverage check found nothing open."

Old: "`/api/side` returns its approved passages beside the classic ones".

New: "`/api/side` returns its published passages (approved, status ok, coverage clear) beside the classic ones".

Left as written: the test name `test_approved_church_passages_appear_beside_the_classic_side` and the fixture note "one approved passage". Those describe the synthetic test, not the product rule.

## Test count

987 tests, 0 skipped, short SHA `47da348` (`47da3482286ab64d3e816ed95672987137a0461f`). Headline in the draft: over 970 tests.

## Word count

Project description: **245 words** (limit 250). The description text was not edited. Count is a whitespace split of the text between the "Project description" heading and "Honest technical claims", same method as `reports/W4-SUBMIT-REFRESH.md`. The heading still says 245.

## Still pending for Patrick (not changed)

- Track: Discipleship & Spiritual Growth.
- Tone: the project description is the same 245 words.
- Tagline: "Ask a question, hear the answer in the preacher's own words."
- Tailscale URL placeholder in `docs/DEMO-SCRIPT.md`: `http://<this machine's tailnet name>:PORT`, fill-in blank unchanged.

`docs/DEMO-SCRIPT.md` still pins live search results and the pre-flight floor to `bbdb1ba` ("at or after"). Those queries were not re-run on `47da348`.

## Not in this commit

`docs/DEPLOY.md`, `README.md`, `app/`, `tests/`, `eval/`, and `reports/W3-*` label/prereg files were not edited. A separate duration-nits checkout was using the shared worktree; its files were not staged.

## gitleaks

`gitleaks` is not on `PATH` and was not found under `/opt`, `/usr`, or the home directory. Not run.

## Head

The commit that adds this file is the branch head. The suite SHA above is the commit the tests ran on, not this report's commit.
