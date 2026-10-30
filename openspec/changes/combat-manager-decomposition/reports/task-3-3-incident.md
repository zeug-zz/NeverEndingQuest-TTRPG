# Task 3.3 Verification Harness Incident and Draft Status

Status: **DRAFT for primary review. Task 3.3 remains unchecked; dynamic parity has not been captured or accepted.**

## Incident record

- The unsafe `tmp/combat_prompt_parity_33/capture_before.py` was created at `2026-10-15T00:00:26Z`.
- At least three real `combat_validation` entries appeared in the master log at local NZDT times `13:01:24`, `13:01:36`, and `13:01:51`; the model/provider identity reported for those entries was `gpt-6-luna`.
- `debug/combat/*FIXTURE_attempt1.json` artifacts and API/root dumps were modified. No pre-run hashes were captured, so exact prior contents and modification attribution cannot be reconstructed.
- Exact total request count and cost are unknown.
- No recent mtime changes were observed in the inspected party, journal, world, campaign, character, encounter, or history files. This is limited negative evidence, not proof that no state changed.
- The attempt timed out at 120 seconds. No PID was available. Process inspection returned EPERM; `nono why /bin/ps read` reported the path as ALLOWED. There is no confirmed path-grant denial and no permission widening was requested or performed.
- Diagnostics were left intact. This report contains no API keys, prompt text, or raw config content.
- The original unsafe full-loop attempt remains **FAIL / not waived**; no evidence in this report reclassifies or clears it.
- Task 3.3 is still unchecked. A successful provider-free pre-extraction baseline is not post-extraction parity verification, and G3 remains incomplete.

## Reviewed guarded pre-extraction capture

The primary's reviewed command was run exactly as `env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tmp/combat_prompt_parity_33/capture_before.py`, with a 30-second cap. It completed successfully after adding only the deterministic fixture `get_current_actor()` response. Guard self-checks passed; all three selected context/prompt cases reached normal prompt output. The real initiative tracker fixture kept the guarded fake fallback unused. No application module, combat loop, provider, or SDK was invoked.

The immediately preceding reviewed run had passed its guard self-checks but stopped at `AttributeError` because the fixture lacked `get_current_actor`; it produced no baseline. The deterministic fake was added and the reviewed command rerun. The earlier unsafe full-loop attempt remains FAIL and is not waived by either guarded run.

Primary-reported protected campaign/data/history/encounter/root-API/debug/master-log file hashes, sizes, and mtimes were unchanged. The selected stage recorded **9 fixture helper calls and 0 write intents per case**; these are observations from `before_outputs.json`, not hardcoded counters. Each case recorded fixture reads for its current player and Scout Kira, the fake roster collector, initiative tracker, current actor, required response, pending enemies, party summary, and active-PC context formatter. The active-PC context names were Acheron, Lidda, and Vitreol respectively. The only real harness artifact writes were confined to this approved scratch directory.

Dynamic pre-extraction fixture prompt hashes (SHA-256; UTF-8 byte length):

| Synthetic case | SHA-256 | Bytes |
|---|---|---:|
| 1-PC PC phase | `74ddf6085ae97c6cdf4db1f6e9c44efbf1215b9f686c8e69f5f5186df55c1abc` | 1842 |
| 4-PC active rotation, unconscious PC | `d8a918288a02bc0bf0ad438ed6956774cbe54f33bcde658ae6ca46fc98813a6b` | 1925 |
| 4-PC enemy phase, synthetic resume ledger | `6b8e0ca216870084f87f23d284142b460bdb5529c871d2f34d9287874538bba4` | 1976 |

Static combat prompt asset SHA-256 values were captured for all 9 files in `tmp/combat_prompt_parity_33/static_before.json`:

| Asset | SHA-256 |
|---|---|
| `prompts/combat/combat_sim_prompt.txt` | `148d4211474c9189ec54b43ee5fa39eb505a3d1a8d284d7d42581e25ccc7e54b` |
| `prompts/combat/combat_sim_prompt_compressed.txt` | `25d87b3116cd0425d59425dd63735aaff587d8c1248f8464037392f0c9c846cb` |
| `prompts/combat/combat_sim_prompt_multipc.txt` | `7f6c4aaa9567208bf0d766e3bf1b5770d3cd8519a31d727ddfe022aafb715957` |
| `prompts/combat/combat_sim_prompt_multipc_compressed.txt` | `b31ad6960e340d8b05eb76849f983533044f503eb88cf82714beb6526412647e` |
| `prompts/combat/combat_sim_prompt_uncompressed.txt` | `3bb128e94901f3810b97191b6db16dee9662976e951620f8fd80f57cc6fed612` |
| `prompts/combat/combat_validation_prompt.txt` | `ca12e479668a623b124efa7aa1777554e2ef25b169bf34240e6fc797f7eb486a` |
| `prompts/combat/combat_validation_prompt_compressed.txt` | `18ac9069aea90e5d5225e4f2c40420c051d19ee378387e8a32f2ebe99e9c2dda` |
| `prompts/combat/combat_validation_prompt_multipc.txt` | `2db539f355904ee88a76bc70e0de611a3a0de0c3c69fd1926de8ae2a0bbdf0eb` |
| `prompts/combat/combat_validation_prompt_multipc_compressed.txt` | `7f905bd2902bc74780eb4f24705d80645d4c5d229f57fe6dda8d9c4f13f84812` |

These captures are synthetic-fixture pre-extraction baselines only. They do not claim byte parity against the extracted package owner; preserve them before any 3.3 product extraction.

## Current draft boundary

`tmp/combat_prompt_parity_33/capture_before.py` is an inert, test-only AST extraction draft. It parses the current owner `core/combat/combat_manager.py` and identifies the post-decision context/prompt sibling suite by semantic AST targets, ending at `user_input_with_note` before history cleanup/provider retry; it uses no source line numbers. Review correction: the extracted statements are now wrapped in a generated test-only function with explicit fixture parameters and an output dictionary. Owner early returns remain function returns, and a required-case early return is a capture failure. Existing manager/helper responses are deterministic fixtures, not imported/instantiated application code.

The harness has explicit fixture cases for 1-PC PC phase, 4-PC active-PC rotation with an unconscious PC, and 4-PC enemy phase with synthetic completed-turn ledger/resume context. NPC, living enemy, dead enemy, history/ledger/resume context, manager/helper responses, and write-intent observations are synthetic or faked. It captures the actual selected owner statements' dynamic state and prompt serialization in memory. The successful guarded run created pre-extraction baselines under this scratch subtree; no post-extraction parity output has been captured.

Before any selected reference statement is compiled/evaluated, the draft installs network/provider denials, config/bytecode read denial, and out-of-scratch filesystem mutation denials. Selected code executes with restricted builtins and an import hook that rejects application/SDK imports; the only optional fake module is the known initiative-tracker dependency, and capture asserts the live manager tracker keeps that fallback unused. AST checks reject dynamic execution/import calls, SDK construction, provider/network attribute roots, and real filesystem mutation calls. All guard denials use a `BaseException`-derived sentinel; self-checks include an old `except Exception` wrapper to prove denials escape. File-write helper fakes record actual write intents. There is no top-level capture run.

The primary review correction was prompted by a source-level `return None, None` in the selected suite, which cannot compile at module scope. The wrapper now preserves that return as a function outcome, exposes only selected stage results/serialization plus helper/write-intent observations, and rejects a required fixture that returns early. Unused prompt-helper globals were removed.

## Primary review checklist

- Confirm semantic AST boundaries delimit the current context/prompt statements after the decision seam and stop before provider retry.
- Inspect guarded operations and ensure all write/rename/mkdir targets outside `tmp/combat_prompt_parity_33/` fail with `GuardDenied` before any executed reference code.
- Review fixture scope, captured helper/write intents, and all required 1-PC/4-PC parity cases.
- Only after review, the primary may run the provider-free harness and compare its resulting baseline against the corresponding post-extraction output. This draft itself makes no captured-parity claim.

## Unrelated work preserved

Source CLI/docs work unrelated to this task was not modified. No goals, task checkboxes, commits, pushes, archives, diagnostics, or campaign files were changed or cleaned up by this draft.
