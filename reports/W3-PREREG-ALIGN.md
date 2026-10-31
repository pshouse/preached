# W3-PREREG-ALIGN: fusion pre-registration aligned with CTO #42 r1 MF1

Branch `docs/w3-prereg-align` from origin/main f1de31e (PR #43 merged, precondition met). Docs only. No change to `src/`, the index, `eval/questions.jsonl`, grades, the label sheet CSV, the KEY or the generator, so the #43 sheet sha256 pin is unchanged. No test needed updating.

## Edits (line numbers in the new `reports/W3-FUSION-PREREG.md`)

- L7: `plain-blind` is not held out for any variant (author read every blind failure; OR-shape rule is close to a long-question detector), may be reported only as an in-sample check; the fresh blind set is the confirmatory test, required before any accuracy claim.
- L8: "not evidence for shipping" → "not evidence for any accuracy claim".
- L9: discloses that `plain-blind` questions were LLM-written (Grok, `llm-written:grok`) and every blind label was proposed by an LLM (Claude), unconfirmed by a person.
- L32: "reported once… as the held-out number" → "as an in-sample check only"; not held out, not confirmatory.
- L40: heading "before any ship" → "before any accuracy claim".
- L42-44: fresh set required before any accuracy claim; wording and labels frozen and committed before any ranker runs on it; provenance field per question; LLM-written disclosure.
- L52 (stop rule 3): no longer uses `plain-blind`; it now gates on the fresh blind set (paired difference not positive, or CI includes zero together with a loss). Rule 4 unchanged.
- L55: new line, `plain-blind` is in-sample and gates nothing; a loss is a warning.
- `reports/EVAL-GRADE.md` §4 (around L258): "next comparison should lead with `plain-blind`" → report it only as an in-sample check; confirmatory test is a fresh blind set frozen before any ranker runs.

Unchanged: the grid {0.5, 0.25}, the OR-shape rule, the selection rule and tie-break, all numbers, and the re-freeze-labels-before-any-run commitment.

## grep for "held-out" / "held out" in reports/ and docs/ (after edit)

- `W3-FUSION-PREREG.md:7` and `:32`: the new text saying `plain-blind` is *not* held out.
- `W3-LABEL-SHEET-BLIND.md:22`: a search term in the leak check of the blind sheet; not about `plain-blind` results.
- `W3-POLISH.md:119`: leave-one-out on abstain-floor fitting; unrelated.
- `W1-B.md:96`: the weighted mix was not tuned on a held-out set (W1 benchmark); unrelated.
- `docs/`: no hits.

No remaining "held-out" or "held out" is applied to `plain-blind` as a positive claim.

## Checks

`uv run python -m unittest discover -s tests`: 940 tests, OK. `uv lock --check`: OK (79 packages). No deps added.
