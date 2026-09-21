# Fork Independence Pivot - Tasks

## 1. Baseline Record

- [x] 1.1 Verify the "Baseline And Evidence" table in `design.md` against live
  repository state and correct any drifted value. Verify with
  `git rev-parse HEAD`, `git rev-parse origin/main`,
  `git merge-base HEAD upstream/main`, `git rev-list --count`,
  `git remote -v`, and `git status --short`. Do not fetch upstream.

## 2. ADR Record

- [x] 2.1 Create `adrs/0031-independent-development-fork.md` with
  `Status: Accepted`, `Supersedes: ADR-0002 and ADR-0030`, and sections for
  context, decision, retained internal boundaries, remote policy,
  attribution/license policy, React vendor policy, and marker policy; link
  ADR-0003 as the rescoped relationship and cite `plans/independent-fork.md`.
  Verify all required metadata fields and section headings are present.
- [x] 2.2 Mark `adrs/0002-merge-safe-tabletop-overlay-architecture.md` as
  `Superseded` with `Superseded by: ADR-0031`, preserving its historical
  rationale and its note that TT-only extraction was a future path. Verify
  metadata fields and unchanged rationale text.
- [x] 2.3 Rescope `adrs/0003-upstream-first-extend-do-not-replace.md`: set
  `Status: Amended` and `Amended by: ADR-0031`; state that extension-first
  design remains an internal maintainability rule while upstream-first
  preservation and merge parity are retired. Verify the amendment note and
  ADR-0031 link.
- [x] 2.4 Mark `adrs/0030-fork-divergence-upstream-as-patch-source.md` as
  `Superseded` with `Superseded by: ADR-0031`, preserving its patch review
  history as historical context. Verify metadata fields and unchanged history
  text.
- [x] 2.5 Update `adrs/index.md`: add ADR-0031 to the list, add an `Amended`
  entry to the status legend, update the ADR-0002/0003/0030 statuses, and record
  ADR-0031 superseding ADR-0002 and ADR-0030 in the supersession map. Verify
  index entries agree with each ADR file's metadata.

## 3. Active Guidance Alignment

- [x] 3.1 Update `openspec/config.yaml`: replace merge-safe/upstream-preservation
  context with independent-fork framing; retain Python ground truth, atomic JSON
  operations, ASCII-only output, SP/MP compatibility, and MUST/SHOULD two-layer
  rules; replace the merge-safety proposal rule with reference/approved-port
  wording; replace the stale OpenRouter router "Current initiative" block with
  the fork independence initiative naming `fork-independence-pivot` and
  `fork-final-upstream-sweep`. Verify the file parses as YAML and contains no
  merge-safe or upstream-preservation requirement.
- [x] 3.2 Update `openspec/frontier_builder_profile.md`: replace the merge-safe
  evolution style preference with guidance that preserves additive
  compatibility only where a fork requirement exists. Verify no merge-safe
  claim remains.
- [x] 3.3 Update `AGENTS.md`: (a) reframe the project overview at line 66 as an
  independent fork originally derived from upstream; (b) reframe the
  plugin-architecture bullets and the "Plugin Architecture & SP/MP Unification
  Roadmap" section so extension boundaries serve ownership/testability, markers
  are lineage documentation, and no upstream-merge procedures remain; (c)
  replace the `#### Upstream Sync Policy (ADR-0030)` policy, the Upstream Sync
  Log, and the `#### Upstream Merge Guidelines (Legacy ...)` section with a
  short `Fork Independence Policy` referencing ADR-0031. Keep the Git Push
  Safety Rules and Module Publication Git Contract unchanged. Do not touch
  historical change-log entries elsewhere in the file. Verify by targeted reads
  of each edited region.
- [x] 3.4 Update `README.md` so the fork relationship reads as independent
  development originally derived from upstream; retain the upstream and fork
  links and the "What This Fork Adds" framing. Verify no merge-safe claim
  remains.
- [x] 3.5 Update `CONTRIBUTING.md` so the repository is described as an
  independently developed fork originally derived from upstream; keep
  extension-file, marker, atomic-JSON, ASCII, and SP-compatibility guidance.
  Verify no merge-safe claim remains.
- [x] 3.6 Update `plans/independent-fork.md` status from "Draft for review" to
  approved with implementation tracked by `fork-independence-pivot` (governance)
  and `fork-final-upstream-sweep` (behavior ports). Verify the status line
  references both change names.

## 4. Verification

- [x] 4.1 Run `openspec validate fork-independence-pivot --strict` and confirm
  the change validates.
- [x] 4.2 Run `.venv/bin/python scripts/check_ascii_compliance.py --summary-only`
  and `git diff --check`; confirm no new violations and no whitespace errors.
- [x] 4.3 Stale-reference scan across active guidance (`AGENTS.md`, `README.md`,
  `CONTRIBUTING.md`, `openspec/config.yaml`,
  `openspec/frontier_builder_profile.md`, `adrs/*.md`, `adrs/index.md`) for
  `merge-safe`, `merge safe`, monthly/routine upstream review language, and
  active upstream-merge policy claims; confirm remaining matches are limited to
  superseded ADR historical text and excluded historical sections.
- [x] 4.4 Confirm the change diff contains only governance/documentation
  artifacts: no changes under `modules/`, `characters/`, `data/`, `config.py`, or
  runtime state paths; no upstream fetch or push command executed;
  `git remote -v` still shows the upstream push URL as `DISABLE`.
