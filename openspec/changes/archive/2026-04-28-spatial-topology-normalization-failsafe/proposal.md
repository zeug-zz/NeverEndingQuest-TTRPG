# Why

Some authored room graphs cannot be safely repaired by coordinates alone within the current 2D cardinal-grid contract. After the tier-contract correction, those cases should fail honestly instead of passing through false Tier 2/Tier 3 layouts. The final module-builder failsafe needs a deterministic way to make these modules structurally valid without depending on an LLM to solve topology.

The practical guarantee is topology normalization: preserve authored rooms, transform impossible direct edges into explicit connector paths, and re-run the same validators. Examples include a mirror portal, trapdoor crawlspace, dimensional threshold, hidden passage, or service tunnel.

# What Changes

- Add a deterministic connector-node remediation path for unresolved spatial edges.
- Convert unsatisfied direct edges into valid paths such as `A <-> Connector <-> B`.
- Emit generated connectors as real module locations or transition nodes with provenance.
- Re-run spatial and map/area parity validation after connector insertion.
- Keep optional LLM involvement advisory only: flavor suggestions may be proposed, but Python owns canonical mutation and validation.

# Capability Scope

- Spatial remediation/build pipeline for module coordinate repair.
- Area/map parity synchronization after generated connector insertion.
- Structured provenance for generated spatial remediation nodes.
- Optional review payload for LLM/human flavor suggestions, if enabled later.

# Non-Goals

- Relaxing the strict Manhattan adjacency rule.
- Allowing same-coordinate rooms without a future `plane`, `layer`, or `dimension` schema.
- Letting LLM output directly mutate canonical module topology.
- Fixing unrelated publication blockers such as monsters, NPC authority, schema completeness, semantic contradictions, or media handoff debt.

# Impact

- Provides a practical 100% route for spatial adjacency failures when connector insertion is allowed.
- Makes formerly impossible coordinate-only graphs publishable by adding explicit traversable spaces.
- Preserves gameplay reachability and facilitator trust because remediation is visible and provenance-tagged.

# Risks

- Connector insertion changes authored topology, even if it preserves reachability intent.
- Too many generated connectors can make a module feel artificial if not named/flavored coherently.
- Existing validators may need area/map parity updates to accept generated nodes consistently.

# Fallback

- If connector insertion cannot produce a valid module, emit `author_structural_debt` with exact blocking edges and no publishable success.
- If LLM advisory flavor fails, use deterministic connector templates.

# Merge Safety and SP/MP Impact

- This is a module-builder/remediation feature and does not change runtime travel validation semantics.
- Generated connector nodes are ordinary module content after build time, so SP and MP runtime can consume them through existing location/transition paths.
