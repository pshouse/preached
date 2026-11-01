# 99-WL-AGENTS-UVCACHE — add UV_CACHE_DIR to the AGENTS.md rule-5 list

## 1. What was done
Branch `chore/w5-agents-uvcache` from origin/main e6c1f96 (clean tree confirmed). Only `AGENTS.md` changed:
- AGENTS.md:51 (rule 5, "Cache safety"): list is now `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME` or `UV_CACHE_DIR`. No read-only-mount claim added.
- AGENTS.md:59 (section 7 item 2): `UV_CACHE_DIR=$(mktemp -d)` added to the full-suite command (before `HF_HUB_OFFLINE=1`), and the sentence now reads "Point `DENO_DIR`, `XDG_CACHE_HOME` and `UV_CACHE_DIR` at temp dirs too". Every other word unchanged.
Both lines verified by reading them after the edit.

## 2. How to run it
`PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=$(mktemp -d) HF_HOME=$(mktemp -d) PREACHED_ONNX_DIR=$(mktemp -d) DENO_DIR=$(mktemp -d) XDG_CACHE_HOME=$(mktemp -d) UV_CACHE_DIR=$(mktemp -d) HF_HUB_OFFLINE=1 uv run python -m unittest discover -s tests`
(run via `env`, which overrode the ambient `UV_CACHE_DIR=/cache/uv`, `XDG_CACHE_HOME=/cache/xdg`, `HF_HOME=/cache/huggingface`).

## 3. Results
Ran 1100 tests in 256s: **OK (skipped=12)**, exit 0.

## 4. /cache before/after
Snapshot (`find /cache -printf '%p %s %T@'`, 132697 entries) before and after the run: ONE difference: `/cache/index/cc-speech.sqlite-shm` mtime changed (1793492570 -> 1793492869; size 32768 unchanged; no paths added/removed). My run pointed every cache var at mktemp dirs, so I did not intend to touch it; I cannot prove the cause. A `-shm` file is rewritten whenever any process opens/reads that SQLite DB (e.g. another agent or a running server on the shared /cache), so a concurrent reader is the likely explanation, but this is unverified. Flagging for CoS.

## Rule-4 grep
`grep -n AGENTS docs/DEPLOY.md tests/test_deploy_alerts.py` returned nothing: no DEPLOY cite points at AGENTS.md, so nothing to re-pin.

## 5. Open issues / dependencies
None. No dependencies added.
