# SP2 offline evidence (orchestrator-owned task 5.1)

Gates (primary-run): `.venv/bin/python -m unittest discover -s scripts -p 'test_mapping_pilot_*.py'` OK; ASCII compliance 0 violations; `openspec validate v2-mapping-pilot-offline --strict` valid; boundary diff limited to `scripts/` and the two mapping-pilot OpenSpec change directories.

D1 live run `d1-20261105-01` (owner-authorized 2026-11-05; production-auto, unpinned):
- Evidence: `tmp/router-rollout/mapping-pilot/d1/d1-20261105-01/` (gitignored; RUN_NOTES.md, selection.json, d1_attempt_ledger.json, d1_audit_sheet.json, d1_owner_audit.csv, modules-before.sha256, console log).
- Selection: 20 locations (Keep_of_Doom 7, The_Thornwood_Watch 6, The_Pumpkin_Kings_Curse 7) recorded at commit f004c9bb before any provider call; source hashes re-verified by the dry run.
- 20 of 60 invocations used; 21 router receipts; resolved models minimax/minimax-m3.1-flash 19, gpt-6-luna 1 (fallback), unknown 1; cost unknown (not zero).
- 11 validated, 9 invalid_layout: 3 door-backed exits with unknown destinations because the source has no door-to-destination binding (AN01, AN02, AA02); 1 known destination marked unknown (AG01); 4 undeclared local-feature references (AE01, NC02, NC03, RO01); 1 unauthored distance field (V03).
- modules/ byte-identical before and after; `git status modules` clean.
- Owner audit sheet: 1048 claim rows (exit 258, exit_side 51, feature 372, location 40, visibility/perceivability/sightline 327); all owner fields blank. Threshold: precision >= 85% with zero invented exits. Pending owner audit at SP4.

M1 packet `m1-20261105-02`:
- Evidence: `tmp/router-rollout/mapping-pilot/m1/m1-20261105-02/` (16 sketches: 5 fixture viewpoints including combat P1/P4, plus 11 validated D1 layouts; 9 invalid D1 layouts omitted with reasons; manifest hashes verified; ratings.csv blank). `m1-20261105-01` is superseded (cosmetic phrasing fix) and must not be rated.
- Threshold: mean >= 3.5 for legibility and usefulness. Pending owner rating at SP4.
