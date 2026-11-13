# Profile characterization

## Coverage and declaration status

The versioned profile set covers eight required fixture-party pairs and their
26 planned rows. All declared startup and resume values remain `MISSING` in
`scripts/live_gate_preflight_profiles.json`. Missing is an honest, supported
profile status: it blocks booking eligibility but does not block the remaining
provider-free tooling tasks. The replacement-only reserve rows were not
activated.

| Fixture-party pair | Planned rows | Characterization outcome | Evidence |
| --- | --- | --- | --- |
| `interior_tavern:p1` | E01-E03 | MISSING; probes failed before measuring calls | `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-e01-p1-startup-02/` (port proof failure), `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-e01-p1-startup-03/` (host not ready) |
| `interior_tavern:p4` | E07-E12 | MISSING; one port-proof failure and one host census failure | `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-e07-p4-startup-01/`, `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-e07-p4-startup-02/` |
| `landscape_village:p1` | E04-E06 | MISSING; host census rejected | `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-e04-p1-startup-01/` |
| `landscape_village:p4` | E13-E18 | MISSING; host lifecycle failed | `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-e13-p4-startup-01/` |
| `transition_tower_approach:p1` | E04-E06 | Startup observed 9 calls at SHA `7e874277`; measured evidence is not portable as a checked-in declaration | `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-tower-p1-startup-01/profile-evidence.json` |
| `transition_tower_approach:p4` | E13-E18 | Startup observed 9 calls at SHA `021a5546`; measured evidence is not portable as a checked-in declaration | `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-tower-p4-startup-01/profile-evidence.json` |
| `combat_stage_tavern_zones:p1` | C01-C04 | MISSING; stub lacked a response for an observed router task | `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-combat-p1-startup-01/` |
| `combat_stage_tavern_zones:p4` | C05-C08 | Startup observed 2 calls at SHA `17d63b07`; measured evidence is not portable as a checked-in declaration | `tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-combat-p4-startup-01/profile-evidence.json` |

The three completed startup bundles have recorded call-evidence SHA-256 values:

- Tower P1: `8908c2e325e0e2289789d4baeda721a553c809e1c9f5b4d99086f0f9f8b71a19`
- Tower P4: `ee0fe4018769f3e125dc3bfe7ce228111088c55027b2fa8ae6417ef33c867046`
- Combat P4: `40f328d3d5c877a56aa13065585790081f9abcca0a6f679ac1b047d80b47f1c9`

These bundles validate in memory only; their absolute interpreter argv and
`PYTHONPATH`, plus gitignored temporary evidence, make them nonportable
declarations. They have not been promoted into the checked-in profile set.
Resume remains `MISSING` for every pair. Bounded resume probes were run only
for `transition_tower_approach:p1`, `transition_tower_approach:p4`, and
`combat_stage_tavern_zones:p4`; those probes found no moved checkpoint. Resume
for the other five fixture-party pairs was not measured. Failed startup
attempts are not evidence of call counts.

This report establishes structural coverage and honest missing-profile
reporting only. It records **no gate PASS** and does not establish booking
readiness; missing profiles continue to block booking.
