# Deferred Production Seed Checklist (Request Withdrawn)

Status: WITHDRAWN by owner clarification, 2026-11-05. The producer-side
document was deleted with owner approval. This consumer copy is retained
only as a deferred checklist; it is not an active request or authorization.

Evaluate the delivered 240-fragment bundle with TITAN- and Module
Builder-shaped scenarios first. Feed evidence-backed schema and retrieval
gaps to NEQ-world, iterate bounded pilot changes, and obtain owner sign-off
on the optimized schema/consumer contract. Only then may the owner separately
authorize full-corpus enrichment/export of roughly 40k fragments. The
original wording below is historical/future acceptance material, not work
to begin now.

Hello NEQ-world team,

NEQ-TTRPG has completed a read-only review of the delivered structured seed
pilot. We are preparing the consumer-side pilot review; this request is not
approval of the pilot, publication clearance, or authorization to import it
into a campaign. Please use the current handover contract in
`plans/neq-world-handover.md`, sections 1-10. Its Appendix A is historical and
must not be used as the current export request.

## Consumer observations to reconcile

The delivered seed main-file hash recorded in the handover is
`6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e`.
The consumer's immutable SQLite-backup copy has SHA-256
`d8a9184c60151d02b19fa8e2e4b18f615904cd02fbd1d6717ca8ef5db25399f6` and is
26,296,320 bytes. The copy was created with SQLite backup rather than as a
byte-copy, and the hashes differ; this is not a claim of logical data change.
Consumer inspection of that copy found
17 tables, 41,216 atoms, 95 profiles, 41,216 statistics rows, 3,944 alignment
profiles, and zero `atom_relations`. It found 4,060 non-null detail cells,
including 240 integer-version-1-shaped JSON envelopes and 229 ordinary JSON
parse failures. The 240 count is not a full validation of the v1 contract.

These counts are a bounded pilot baseline, not a full-export acceptance quota.
The handover reports 364 unresolved public references and 13 ambiguous
polymorphic references outside the selected pilot scope; please replace these
producer-reported pilot findings with a full-corpus, hash-bound inventory for
the proposed export. The current handover also states that the delivered seed
has no `source` columns on the specified alignment/conflict/deity bridge tables.
Do not rely on the superseded appendix's contradictory schema descriptions or
invent source identities to fill that gap.

## Future bundle and evidence checklist (not currently requested)

Please provide one self-contained public bundle, tied together by exact hashes:

1. A closed SQLite seed file that needs no WAL/SHM sidecars, plus a manifest
   with exact SHA-256, byte size, schema version, content/export version,
   exporter/build version, build time, and every user-table row count.
2. Exact delivered DDL, indexes and constraints; explain every schema delta
   from the pilot, including atom detail columns and any source/derivation
   fields. Keep the detail envelope version distinct from SQLite metadata
   version. Report stable-ID policies for changed, merged and deleted IDs,
   with public-safe mappings only.
3. Integrity and foreign-key results, plus semantic validation of every
   supported public reference namespace. Report unresolved and ambiguous
   totals by namespace and location without exposing private IDs, paths, or
   inaccessible source identities. State the exact public target keys.
4. Full-corpus coverage and validation distributions by table, atom type,
   entity kind, profile kind, detail group, alignment state and affinity basis.
   Include missing, invalid, legacy and unsupported detail counts. Clearly
   distinguish producer validation from consumer verification.
5. Definitions and units for weights, `support_count`, `avg_weight` and
   `variance`; explain whether support counts independent source evidence or
   repeated extraction. Clarify provenance and derivation classes. Do not
   present copied summaries as independent evidence.
6. Preserve v1 `content_supported` evidence separately from ordered
   `extensions[]`; report their derivation labels and exact public references.
   Keep invalid or legacy detail compatible with base-atom fallback. Do not
   use label or textual-similarity joins, and do not infer relations.
7. Report real `atom_relations` if present, with direction, meaning, weight,
   confidence and derivation. Zero relations are acceptable if explicitly
   reported with the intended composition fallback.
8. Provide bounded worked retrieval examples using actual public IDs, with
   deterministic inputs, exact selected IDs, expected outputs, validation
   results and hashes. Include the six pilot capability areas if approved
   material supports them; identify synthetic examples as synthetic.
9. State rights/publication screening status, public-safe provenance and
   redistribution limitations. A pilot prose review or anonymization claim
   alone is not rights clearance. Do not include private campaign history,
   credentials, private source text, local paths, private identifiers, or
   unapproved source-book identities.
10. Describe a reproducible regeneration procedure and explain any expected
    byte-level nondeterminism. If bytes cannot be reproducible, provide a
    deterministic logical-content fingerprint as well as the exact delivered
    file hash.

Please do not add unsupported relations, fabricate unavailable coverage,
rewrite the full corpus solely to satisfy uniform enrichment, or change the
existing consumer runtime database. Optional compatibility/dependency/
consequence relations should be proposed only if the pilot demonstrates a
specific retrieval-quality need, with a versioned backward-compatible design.

## Consumer boundary

NEQ-TTRPG owns campaign identity, existing-runtime schema adaptation, import
and conflict policy, retrieval authorization, campaign instantiation,
save/restore, and gameplay integration. The seed remains a reusable,
read-only catalogue, not campaign history or a mechanical authority. No import
or runtime test has been performed for this request. Any consumer import will
first use disposable, consistent copies; an installed-campaign operation would
require separate owner authorization after copy-based tests and a proven
backup/rollback path.

When production execution is separately authorized after schema sign-off,
agree the bundle handoff and validation evidence with NEQ-world. The earlier
delivery approval does not authorize this job; the owner withdrew the
premature request. Producer implementation and publication retain their
own approval and audit requirements.
