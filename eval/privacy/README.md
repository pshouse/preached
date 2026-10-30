# Name-redaction eval sets

Synthetic sermon-like sentences for `preached.privacy`. Every private name is
invented. No real congregant, no Gaston Community Church material.

**All four sets (dev, blind1, blind2, blind3) are synthetic and LLM-written.**
Real-sermon performance is unmeasured. A human-written or human-audited blind
set is pending. Per-word Wilson intervals (blind3 recall 0.926 [0.886, 0.952],
false redaction 0.155 [0.121, 0.197]) understate the uncertainty, because names
cluster within sentences.

| Set | Lines | Private words | Kept-name words | Written by | Status |
|---|---|---|---|---|---|
| `dev.jsonl` | 184 | 115 | 170 | the module's author | tuning |
| `blind1.jsonl` | 184 | 144 | 220 | separate agent, no repo access | blind for the first run, then tuning |
| `blind2.jsonl` | 234 | 170 | 285 | separate agent, no repo access | blind for one run, then tuning |
| `blind3.jsonl` | 272 | 242 | 354 | separate agent (unrecorded LLM; the model is not named in any commit, file or log), no repo access | blind: scored once on frozen rules (e980f36) |

Each line is `{"id", "category", "text"}`. Categories: `prayer_request`,
`announcement`, `testimony`, `scripture_narration`, `church_history`,
`quoted_author`. In `text`, `[[...]]` wraps a private name (must become
`[name]`) and `{{...}}` wraps a biblical, historical or public name (must
stay). Titles sit outside the brackets ("Sister [[Jane]]"). Everything else
is unmarked.

## Method

`evaluate.py` strips the markup, splits on spaces into Whisper-style word
records (0.3 s apart) and calls `redact`. Scoring is per word:

- recall = private words redacted / private words (target >= 0.98)
- false-redaction rate = kept-name words redacted / kept-name words (target <= 0.02)
- other-word rate = unmarked words redacted / unmarked words

A word counts as redacted when its output contains `[name]`. The script also
checks that timing and word count are unchanged.

A blind set is scored once on rules frozen in a commit, and that number is
recorded (`results/`). After anyone has looked at its errors it is only a
tuning set. Label fixes are listed in the commit that made them.

## Run

    python3 eval/privacy/evaluate.py eval/privacy/dev.jsonl eval/privacy/blind1.jsonl eval/privacy/blind2.jsonl eval/privacy/blind3.jsonl
    python3 eval/privacy/evaluate.py eval/privacy/blind3.jsonl --errors   # every miss and over-redaction

NER baseline (spaCy, not a dependency; see the script's docstring for the
throwaway venv):

    /cache/venvs/w3-priv-ner/bin/python eval/privacy/ner_baseline.py en_core_web_sm eval/privacy/blind3.jsonl
