# W3-PREREG-S2: record the labeller's S2 answer in the prereg

Patrick answered CTO #43 S2 on 2026-10-31 (8:22 AM ET, to Chief of Staff): "no". He did not open either earlier unblinded label sheet (f3d2142, 3b9441b). Self-reported; not independently verifiable.

## Changes (docs only)
- `reports/W3-FUSION-PREREG.md`: the PENDING line now reads "Labeller exposure to earlier unblinded sheet: none. Patrick (the labeller) stated on 2026-10-31 that he did not open either earlier unblinded sheet (f3d2142, 3b9441b). Self-reported; not independently verifiable."
- `reports/W3-LABEL-SHEET-R2-FIX.md`: the S2 entry quoted the PENDING placeholder; it now says the line was left unanswered (not guessed) and was answered 2026-10-31.
- Label sheet, KEY and generator untouched; sha256 pin unchanged.

## Checks
- Test suite: OK.
- `grep -rI "PENDING Patrick"` (excluding .git): no matches.
- origin/main already merged in; no rebase or force-push.
- No sandbox.sh or gh in this environment: plain git in a worktree. PR #47 open state could not be checked via gh; the remote branch head was 8dc08e6c32bf946edde324ecf3d60018fc138abd as expected.

## Diff
    diff --git a/reports/W3-FUSION-PREREG.md b/reports/W3-FUSION-PREREG.md
    index 6c3d79c..e4d7021 100644
    --- a/reports/W3-FUSION-PREREG.md
    +++ b/reports/W3-FUSION-PREREG.md
    @@ -15,7 +15,7 @@ Branch `docs/w3-label-sheet`. Date: 2026-10-31. Source: §7 proposal 1 of `repor
     **Labeller access and limitations (CTO #43 r2).**
     
     - The labeller gets only `reports/W3-LABEL-SHEET.csv`, not the repo. `reports/W3-LABEL-SHEET-KEY-source.json` (renamed from `w3_label_sheet_source.json`) holds the withheld data and must not be opened by the labeller; git history (f3d2142, 3b9441b) still contains the earlier unblinded sheets.
    -- Labeller exposure to earlier unblinded sheet: PENDING Patrick's answer. (If Patrick opened an earlier unblinded sheet, record it here as a limitation.)
    +- Labeller exposure to earlier unblinded sheet: none. Patrick (the labeller) stated on 2026-10-31 that he did not open either earlier unblinded sheet (f3d2142, 3b9441b). Self-reported; not independently verifiable.
     - Style confound: 4 of the 10 blind-written (`plain-blind`) questions are all-lowercase, with no apostrophes, commas or question marks (a single period at most); none of the 8 plain questions is all-lowercase. A labeller can therefore tell some blind-written questions from plain ones by style. Counts verified from the KEY (groups `plain-blind` vs `plain`).
     
     ## Frozen change
    diff --git a/reports/W3-LABEL-SHEET-R2-FIX.md b/reports/W3-LABEL-SHEET-R2-FIX.md
    index cdd5507..cb4ee92 100644
    --- a/reports/W3-LABEL-SHEET-R2-FIX.md
    +++ b/reports/W3-LABEL-SHEET-R2-FIX.md
    @@ -22,7 +22,7 @@ After reverting: `--check` "up to date", tests OK.
     
     ## Should-fixes
     - **S1:** `reports/w3_label_sheet_source.json` renamed to `reports/W3-LABEL-SHEET-KEY-source.json` (git mv); references updated; the KEY and prereg say do not open it, the labeller gets only the CSV not the repo, and f3d2142/3b9441b still hold unblinded sheets.
    -- **S2:** prereg line "Labeller exposure to earlier unblinded sheet: PENDING Patrick's answer". Not guessed.
    +- **S2:** prereg line "Labeller exposure to earlier unblinded sheet" was left unanswered, not guessed (answered 2026-10-31, see W3-PREREG-S2).
     - **S3:** verified from the source: 10 `plain-blind` questions, 4 all-lowercase (p-021, p-030, p-002, p-008); 8 `plain`, 0 all-lowercase. **Correction to the CTO wording:** those 4 are not punctuation-free, each has a period (no apostrophes, commas or question marks), so the prereg says that.
     - **S4:** new test checks every question/chunk cell exactly against the source and scans all cells for `<!--`, `-->`, tags and control/format/exotic-space characters.
     

Head SHA: see the commit following the one that added this report (head reported in the hand-off message).
