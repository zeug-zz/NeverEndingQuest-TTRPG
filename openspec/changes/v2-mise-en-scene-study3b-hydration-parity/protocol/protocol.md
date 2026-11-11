# Study 3b Provider-Free Protocol

## Identity and authority

This isolated protocol is bound to study ID `mise-en-scene-study3b-20261111`
and version `neq.llm_staging_study3b_delta.v1`. It records a fixed request
contract only; this protocol, its manifest, and its generation configuration do
not authorize dispatch, create an allocation, read credentials, or call a
provider.

The Study 3b manifest binds this protocol and its generation configuration by
SHA-256. The protocol module pins the exact manifest hash. The manifest also
records the read-only Study 3 manifest and protocol provenance. Study 3b request
content may reuse only the existing hash-verified Study 3 source bindings and
templates; request identity, envelope, scene order, and attempt limits come from
this Study 3b protocol/configuration. Prior runtime state, response artifacts,
ledgers, and allocations are not inputs.

## Fixed scene and attempt contract

There are exactly three scenes in this order:

1. `into_the_deepvault:scene:ha003-i02`
2. `into_the_deepvault:scene:sd005-i03`
3. `xhalruuns_masquerade:scene:tsu001-ao02`

The cap identity is the Study 3b study ID, with at most one attempt per scene
and three attempts total. Reordering scenes, changing either identity, or
changing either limit invalidates the contract.

## Fixed generation and transport envelope

The generation configuration fixes OpenRouter `openai/gpt-6-luna`,
`max_tokens=16384`, and a 720-second timeout. The remaining request fields are
also pinned in `generation-config.json`. Retries, reruns, fallback, availability
GET, redirects, and continuation are prohibited. The model request is
provider-free testable; no network access is part of protocol construction or
verification.

## Hash and privacy boundary

Protocol and configuration hashes cover their exact stored UTF-8 bytes. The
manifest hash is pinned in the Study 3b protocol module rather than self-listed
in the manifest. Any missing, changed, reordered, or identity-mismatched
artifact fails closed before request construction. All run/evidence allocation
and dispatch work is outside this protocol task.
