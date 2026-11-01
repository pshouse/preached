# 99-XVD-PARITY-OMARCHY-HOST

Branch: `docs/w5-parity-omarchy-host`, from origin/main `ebc058de95a3c8b6eb3ef51332702c3f8993c3be` (moved past 484e682; its rows kept as they are). Doc commit: `c8ee83840fa67c41affe78a9ac315b485da32eb7`. The head is the later commit that adds this report.

## 1. What was done
Added the omarchy host baseline block (label line, field table, 14 cells, one sentence) to `docs/PARITY.md` after the reviewer-box block and its history paragraphs, values copied character for character. Edited the "Other hosts" sentence minimally: omarchy is now recorded above; the CTO box still needs its own baseline. Host gate command and CI check untouched.

## 2. How to run it
```
T=$(mktemp -d /tmp/pt.XXXXXX); mkdir $T/{cache,onnx,hf,deno,xdg,uv,torch,uvpy,home,venv}
PREACHED_CACHE=$T/cache PREACHED_ONNX_DIR=$T/onnx HF_HOME=$T/hf DENO_DIR=$T/deno XDG_CACHE_HOME=$T/xdg UV_CACHE_DIR=$T/uv TORCH_HOME=$T/torch UV_PYTHON_INSTALL_DIR=$T/uvpy HOME=$T/home UV_PROJECT_ENVIRONMENT=$T/venv ORT_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 uv run python -m unittest tests.test_parity_hash -v
```

## 3. Results and numbers
Commit `c8ee83840fa67c41affe78a9ac315b485da32eb7`, host `preached-sandbox`: `Ran 16 tests in 17.498s` / `OK` (test_doc_records_this_harness passed). tests/test_parity_hash.py not edited.

/cache snapshot (`find /cache -xdev -printf '%p\t%s\t%T@\n' | LC_ALL=C sort`): before 132824 lines, sha256 `3ca707d7aba4f2aa682a6497f9e481bad4c8087d9304142444a746ace64bca64`; after 132824 lines, same sha256; diff: none. The real /cache was only listed, never opened.

`git diff --stat origin/main...HEAD` (doc commit; the report file is added by the head commit):
```
 docs/PARITY.md | 26 +++++++++++++++++++++++++-
 1 file changed, 25 insertions(+), 1 deletion(-)
```
The existing reviewer-box rows are unchanged: `git diff origin/main...HEAD -- docs/PARITY.md` has only added lines plus the one edited "Other hosts" paragraph (its single removed line). DEPLOY.md cites are untouched (no cited file edited).

## 4. Open issues, risks, exclusions
The omarchy values are CTO-supplied and not recomputed here (the real index is not visible to this sandbox). The CTO box baseline is still missing. No gh in the sandbox: PR opened by hand.

## 5. Dependencies added
None.

## PR BODY
Records the omarchy host parity baseline (main 484e682, index 198339132f68…, model 3861025a…, harness 9bbe1a503f36136f) in docs/PARITY.md, and updates the "Other hosts" sentence to say omarchy is recorded and the CTO box still needs its own. Docs only; reviewer-box rows unchanged (diff is added lines plus the one edited sentence). DEPLOY cites untouched.

- Branch `docs/w5-parity-omarchy-host`, base origin/main `ebc058de95a3c8b6eb3ef51332702c3f8993c3be`
- `git diff --stat origin/main...HEAD`: docs/PARITY.md (+ this report)
- `tests.test_parity_hash`: Ran 16 tests in 17.498s, OK (sandbox `preached-sandbox`, commit `c8ee83840fa67c41affe78a9ac315b485da32eb7`)
- /cache listing before/after: 132824 lines each, sha256 3ca707d7…ca64, no diff
