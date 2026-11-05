# NEQ-world Producer Request: Local Handoff Receipt

Date: 2026-11-05. Owner approved delivery in this Overseer session.

Disposition: WITHDRAWN later on 2026-11-05 after owner clarification.
The original, unchanged producer-side request was deleted with explicit
owner approval (its hash matched the value recorded below). The consumer
copy now states the withdrawal and retains only deferred acceptance
considerations. No producer acknowledgement or work is claimed.

The 240-fragment consumer evaluation must inform optimized schema sign-off
before separately authorizing the full roughly 40k-fragment production job.
The following receipt records the earlier handoff historically, not a
currently actionable request.

- Consumer source: `plans/v2-memory-pilot-p0/producer-request.md`.
- Producer destination:
  `../NEQ-world/plans/neq-ttrpg-full-seed-request-20261105.md`.
- Source and destination compared byte-identical with `cmp`.
- SHA-256:
  `c51078b1d6591d9b29979f67501184252bfdb993bc97f64c959831a8a5a3fbd2`.

This is a local document handoff, not a message delivered to a running
producer session. No receipt, acceptance, export work or delivery date from
the producer is claimed. The destination no longer exists; do not recreate
or act on that request as a current production task.

Only this new request document was added in NEQ-world. Existing dirty files,
producer databases and source materials were not changed. No commit, push,
provider call, seed export, campaign import or publication was performed.

Independent consumer verification used only disposable snapshots:

- Runtime snapshot SHA-256:
  `fb11f6089293a4b27aeaedd9680c38afb5f397517a0cd02073d3e87085abd5c5`;
  18,486 events, 18,484 journal entries, 55,516 links.
- Seed snapshot SHA-256:
  `d8a9184c60151d02b19fa8e2e4b18f615904cd02fbd1d6717ca8ef5db25399f6`;
  41,216 atoms, 95 profiles, 41,216 statistics, 3,944 alignment profiles,
  zero relations.
- Each snapshot: `PRAGMA quick_check` returned `ok` and
  `PRAGMA foreign_key_check` returned no violations, opened read-only with
  `mode=ro&immutable=1` using Python sqlite3. No installed database queried.

These checks corroborate the audit's snapshot identities and aggregate
counts, not full semantic validation or source/copy logical equivalence.
