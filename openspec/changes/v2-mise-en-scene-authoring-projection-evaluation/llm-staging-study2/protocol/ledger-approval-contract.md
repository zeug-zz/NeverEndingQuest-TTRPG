# Study 2 Ledger and Approval Contract (S2.3)

## Authority boundary

The current primary record is `campaignB.md`, ruling
`neq-study2-plan-confirmed-20261109`. It approves provider-free preparation
only and records **NO CALLS**. It is not an execution approval, and its ID is
rejected by the execution client. No Study 2 execution-approval JSON, approval
hash pin, initialized ledger, credential access, or provider dispatch is
created by S2.3.

The execution API is implemented so that a later, separately reviewed primary
authority record can supply the two approval document hashes and its distinct
execution ruling ID. Local approval JSON is untrusted input, not a
self-authenticating authority record. A caller must provide `ApprovalPins`
whose values were checked against the primary owner/Overseer record outside
these JSON files. Missing pins, missing files, invalid fields, or any hash or
binding mismatch fail before reservation, credential lookup, or HTTP.

## Immutable identities and paths

- Fixed study ID: `mise-en-scene-study2-20261109`.
- Fixed study root: `tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2/`.
- Fixed studywide ledger: `study-attempt-ledger.jsonl` at that root; it is never
  placed under a run directory.
- Per-run records: `runs/<run-id>/`; the reviewed run root is bound as
  `<fixed-study-root>/runs/<run-id>`.
- Scene order and cap: `ha003-i02`, `sd005-i03`, `tsu001-ao02`; exactly three
  reservations total, in that order, one per scene.
- Study 1's ledger and runtime remain separate and read-only.

The client has no public ledger-path or run-root override, and `Study2Ledger`
has no root-path constructor argument. Both resolve the fixed study root from a
module constant. An alternate run ID uses the same fixed studywide ledger and
cannot reset the cap. An alternate root cannot be selected through the API.
The first ledger header binds the fixed study ID/root, manifest, complete
artifact-hash map, model, protocol version, historical availability hashes,
both approval hashes, and the external authority record ID. Each reservation
and result separately records the run ID and its fixed-root run path; run
identity is intentionally excluded from the studywide header and approval
records.

Ledger initialization is an explicit `Study2Client.initialize_ledger()` call
after the frozen manifest and both approvals validate. It uses exclusive file
creation, writes only the empty bound header, and fsyncs both file and
directory. Existing, empty, pending, corrupt, truncated, symlinked, or
identity-mismatched ledgers are never reinitialized. `send_once()` refuses a
missing ledger; it does not create one. Reservation is appended and fsynced
under thread and process locks before transport credential access. A pending
reservation blocks all replay. No retries, per-run cap, alternate-root reset,
fallback, continuation, redirect, stream, tools, model list, or extra reasoning
controls are supported.

## Approval record shape

Files, when independently authorized in the future, are expected at these
fixed runtime paths:

- `owner-cap-approval.json`
- `overseer-step-a-approval.json`

They have the closed key set below; the role-specific schema and status differ.
Every shared field is checked against the exact frozen Study 2 manifest and
the externally pinned execution ruling.

```json
{
  "schema": "neq.llm_staging_study2_owner_cap_approval.v1",
  "status": "APPROVED_STUDY2_CAP",
  "review_status": "OWNER_APPROVED",
  "study_id": "mise-en-scene-study2-20261109",
  "attempt_cap": 3,
  "model_id": "openai/gpt-6-luna",
  "endpoint": "https://openrouter.ai/api/v1/chat/completions",
  "manifest_sha256": "<sha256 of exact frozen manifest bytes>",
  "protocol_version": "neq.llm_staging_study2_delta.v1",
  "protocol_sha256": "<sha256 of exact Study 2 protocol bytes>",
  "availability_attestation_sha256": "<sha256 of exact historical attestation bytes>",
  "availability_raw_listing_sha256": "d94d8370997bb6a32c8265d0c5368d98c121355ebed0c51698539d81e32bdc13",
  "scene_order": [
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02"
  ],
  "study_root_relative": "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2",
  "authority_record_id": "<distinct execution ruling, not neq-study2-plan-confirmed-20261109>",
  "approved_by": "<owner identity>",
  "approved_at_utc": "<UTC timestamp ending Z>"
}
```

The Overseer document uses schema `neq.llm_staging_study2_overseer_step_a_approval.v1`,
status `APPROVED_STEP_A`, `review_status: "PASS"`, and `approved_by: "overseer"`;
its other fields and closed key set are identical. `ApprovalPins` carries the
SHA-256 of each complete approval document plus the distinct external ruling
ID. The client verifies the bytes against these pins before it checks fields.
It never derives trust pins from the local JSON.

## S2.4 manifest input expected by the client

`staging-manifest.json` is materialized by S2.4 in the Study 2 protocol
directory. The client loads it and fails closed when it or any frozen artifact
is missing; it never synthesizes a prompt, schema, parameter file, manifest, or
approval. The manifest uses the following exact top-level fields:

```json
{
  "schema": "neq.llm_staging_study2_manifest.v1",
  "study_id": "mise-en-scene-study2-20261109",
  "protocol_version": "neq.llm_staging_study2_delta.v1",
  "status": "FROZEN_FOR_REVIEW",
  "scene_order": ["<the exact three approved scene IDs in order>"],
  "attempt_cap": 3,
  "endpoint": "https://openrouter.ai/api/v1/chat/completions",
  "model_id": "openai/gpt-6-luna",
  "availability": {
    "raw_listing_path": "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/availability-check/model-listing.json",
    "raw_listing_sha256": "d94d8370997bb6a32c8265d0c5368d98c121355ebed0c51698539d81e32bdc13",
    "attestation_path": "<the fixed Study 1 protocol availability-check.json path>",
    "attestation_sha256": "<sha256 of exact historical attestation bytes>"
  },
  "artifacts": {
    "protocol": {"path": "<fixed Study 2 protocol.md path>", "sha256": "<sha256>"},
    "input_bindings": {"path": "<fixed Study 2 input-bindings.json path>", "sha256": "<sha256>"},
    "output_schema": {"path": "<fixed Study 2 output-contract.schema.json path>", "sha256": "<sha256>"},
    "system_prompt": {"path": "<fixed Study 2 system-prompt.txt path>", "sha256": "<sha256>"},
    "task_prompt": {"path": "<fixed Study 2 task-prompt.txt path>", "sha256": "<sha256>"},
    "generation_config": {"path": "<fixed Study 2 generation-config.json path>", "sha256": "<sha256>"},
    "availability_attestation": {"path": "<fixed Study 1 protocol availability-check.json path>", "sha256": "<same attestation hash>"}
  },
  "scenes": [
    {
      "scene_id": "<approved scene ID>",
      "source_packet": {"path": "<frozen Study 1 source packet path>", "sha256": "<frozen hash>"},
      "expected_bundle": {"path": "<frozen Study 1 expected bundle path>", "sha256": "<frozen hash>"}
    }
  ]
}
```

There must be exactly three scene rows in approved order. Each source/expected
path and digest is re-derived from the frozen Study 1 bindings and compared to
the manifest. Artifact paths are fixed by role; the client hashes the actual
protocol, bindings, schema, prompts, config manifest, and historical
availability attestation bytes. The manifest itself is bound by its raw-byte
SHA-256 in both approval records and the ledger.

The separate `generation-config.json` is a closed object with schema
`neq.llm_staging_study2_generation_config.v1` and exactly these fields:
`schema`, `endpoint`, `model_id`, `temperature`, `top_p`, `frequency_penalty`,
`presence_penalty`, `max_tokens`, `timeout_seconds`, `stream`,
`response_format`, `tools`, `tool_choice`, and `provider`. `max_tokens` and
`timeout_seconds` are positive measured integers selected and frozen by S2.4;
the transport has no 4096-token or 180-second default. `stream` is false,
`response_format` is JSON object, `tools` is empty, `tool_choice` is `none`,
and `provider` is exactly `{"allow_fallbacks": false}`. No model list, retry,
continuation, or reasoning field is accepted.

The frozen task prompt must contain exactly one each of
`{{SCENE_ID}}`, `{{INPUT_REFS_JSON}}`, `{{SOURCE_PACKET_JSON}}`,
`{{EXPECTED_BUNDLE_JSON}}`, and `{{OUTPUT_SCHEMA_JSON}}`. The prompt can include
canonical source/topology context, but the model response remains the closed
delta-only contract; the deterministic gate retains authority over source,
expected bundle, and topology.

The S2.4 sizing report is a preparation record only. Its byte-based estimates
are marked approximate, its numeric cost is marked `ESTIMATE`, and no report or
manifest status substitutes for either future external approval.

## Guarded transport API

- `Study2Client(run_id, approval_pins)` is constructed without config, network,
  or filesystem writes. `build_request(scene_id)` reads hash-bound frozen
  inputs only and fails when S2.4 artifacts are absent.
- `initialize_ledger()` validates the manifest and both external approval pins
  before exclusive header creation. It is never called implicitly.
- `send_once(scene_id, transport=...)` accepts only the guarded
  `OpenRouterTransport`; tests may inject fake HTTP and a fake configuration
  object into that adapter. A direct adapter call refuses before credential
  lookup or HTTP.
- After reservation, a one-use capability binds the run, scene, attempt,
  request hash, and generation-config hash. The adapter consumes it before
  checking endpoint/model/parameters or reading `config.OPENROUTER_API_KEY`.
- The adapter sends one POST only, uses the frozen measured timeout, disables
  redirects, and imports `config` lazily after the capability and hash checks.
  Tests patch socket/urllib access to fail; no test loads the real config.
- Clean provider response bytes are stored byte-for-byte under the reviewed
  run root. The read-only Study 1 credential redactor is reused; any secret
  echo is sanitized and its receipt identity is deliberately invalidated.
  Ledger entries contain bounded hashes and actual returned model/provider/
  generation/usage metadata, including numeric cost fields when present, but
  never response prose, credential text, or exception text. Usage requires
  top-level nonnegative integer `prompt_tokens`, `completion_tokens`, and
  `total_tokens`; a top-level `is_byok` boolean is preserved exactly when
  present. Optional cost and bounded nested detail values must be finite,
  nonnegative numbers; other boolean or string metadata fails closed.
- Missing/mismatched model, provider, generation ID, or usage consumes the
  reservation and stops the study. HTTP errors and transport failures consume
  their reservation and cannot be retried; pending/interrupted reservations
  remain unavailable for replay.

The tests use synthetic manifests, approval records, temporary ledgers, fake
HTTP, and fake config under project-relative
`tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2/test-scratch/`.
They do not create a Study 2 execution approval file or real ledger and do not
write into Study 1 runtime.

Any adapter exception, including a credential-loader or HTTP exception, is
recorded as a bounded `transport_failure` result with `stop_study: true`. The
underlying exception and its message are not chained into the client-visible
error or persisted. This deliberately conservative stop is not a retry or
continuation policy. A non-200 HTTP response is also recorded with
`stop_study: true`; later scene calls cannot continue past either failure. This
preparation authority still permits no execution calls, and no continuation
path exists to resume after a failure.
