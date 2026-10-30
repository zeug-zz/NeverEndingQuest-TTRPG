# V3 Vision: A MUD for the 21st Century

Status: ROUGH FUTURE VISION - not an implementation plan or active `/goal`.

Recorded: 2026-10-26.

Horizon: at least a year away at the time of this discussion, and only after a
stable v2 game server is reached. This is an aspiration, not a release date or
delivery commitment. Reaching the horizon does not automatically authorize work.

## 1. Vision

Evolve NeverEndingQuest toward a persistent, AI-mediated multiplayer roleplaying
platform: a MUD for the 21st century, with graphics, shared narratives,
open-ended gameplay, and user-generated adventures.

Players join through thin browser clients. Authoritative Python game servers
host campaigns that can remain available independently of a facilitator's
laptop or browser. A community layer helps people find groups, arrange sessions,
share approved campaign stories, and discover a central published module catalog.

Eventually, selected campaigns might participate in a connected persistent
world. That is a further possibility, not a requirement for hosted campaigns.

## 2. Prerequisite: finish and stabilize v2 first

This vision follows, rather than competes with:

- The current LLM-router/combat refactor and its verification.
- The OpenTunnel-first React client and game-server build.
- TITAN integration and the intended narrative/world-memory capabilities.
- Mapping, movement, and coherent persistent world state.
- Stable gameplay, persistence, recovery, and internet test-player experience.

Relevant planning inputs:

- [V2 server/client/network plan](../v2-server-client-network.md).
- [TITAN Game Engine master plan](../v2-titan-game-engine.md).

These links provide context, not claims that those capabilities are implemented
or verified. Active OpenSpec artifacts and accepted ADRs remain authoritative.

**V2 should leave this future open, not implement it in advance.** No account
platform, multi-tenancy framework, public CMS, shared universe, or speculative
database migration is added to v2 scope by this document. Revisit only after
stable v2 and a separate owner decision.

## 3. First evolution: a persistent hosted campaign

Move one authoritative campaign runtime onto a Linux VPS while retaining the
React client contract and Python ownership of game mechanics and durable state.

OpenTunnel could continue as the access transport, with its agent on the VPS.
A secured direct HTTPS gateway could also become appropriate. Keep transport
separate from gameplay so either deployment can serve the same thin clients.

Always-on hosting needs explicit operational design:

- Process supervision, health checks, restart recovery, and maintenance.
- Persistent storage, backups, and tested restoration.
- Authentication, authorization, secure updates, and private credentials.
- Resource limits, bounded queues, LLM quotas, and spending controls.
- Running, paused, stopped, and recovering campaign states.

24/7 availability does not mean continuous LLM activity or unattended world
simulation. Idle campaigns should not generate work merely because they are
reachable. Browser disconnects must not implicitly end the server session.

## 4. Separate platform, facilitator, and player authority

Potential roles:

| Role | Responsibility |
| --- | --- |
| Platform operator | Hosting, service administration, updates, resources, incident response |
| Campaign facilitator/DM | Campaign configuration, invitations, session control, moderation |
| Player/controller | Authorized gameplay participation and eventual PC control |

One person may hold several roles without needing several accounts. Every
operation still requires the appropriate server-enforced capability; a different
page or hidden button is not authorization.

Illustrative facilitator flow:

1. Sign in to a bounded campaign management interface.
2. Select/create a campaign and configure its session.
3. Invite players and start or resume the campaign.
4. Enter the thin player interface and play their own PC.
5. Return to facilitator controls when needed; leaving either browser view does
   not stop the campaign.

Remote facilitator access is a later secured feature, not permission to expose
the current local host console or grant campaign owners general VPS access.
Player/PC assignment may evolve beyond v2's socially coordinated shared active
PC; its ownership and contention rules need separate design.

## 5. Concurrent campaigns: isolated runtimes first

Start with a process or container per campaign rather than adding a campaign ID
to the current global state and calling the application multi-tenant.

```text
Identity and campaign directory
             |
Authenticated access boundary
       /                 \
Campaign A             Campaign B
Python runtime         Python runtime
Private state          Private state
Player clients         Player clients
       \                 /
     Shared published module catalog
```

Each campaign needs isolated characters, party/encounter/world state, memory,
transcripts, journals, private media, sessions, caches, queues, and budgets.
Separate directories are insufficient if mutable globals or unrestricted
filesystem access still cross campaign boundaries.

Preserve one authoritative runtime per campaign and the repository's 1-PC
regression floor. Capacity must be measured; provider quotas and inference cost
may constrain a service before ordinary web traffic does.

## 6. Community, discovery, and narrative publication

A separate web/community service could support group discovery, meetups,
discussion, module showcases, and public campaign narratives.

WordPress is one possible publishing/community foundation, not a selected
dependency. Begin by evaluating a single community site. Multisite may make
sense if groups need separately administered publication sites, but it is not
game-server campaign isolation and does not replace NEQ authorization.

Keep three boundaries:

- NEQ owns authoritative gameplay and campaign access.
- The community service owns discussion, discovery, and published content.
- A narrow publishing integration exports only explicitly approved material.

The community/blog service must not be required for a running game to proceed.
Identity federation, if useful later, needs an explicit trust and revocation
design rather than shared database access.

### Journal-to-blog publication

Extend the draft journal idea through a reviewable publishing pipeline:

```text
Private gameplay -> draft journal -> facilitator review -> public narrative
```

Do not mirror raw transcripts or private memory by default. Publication needs
participant consent, audience/visibility controls, spoiler handling, redaction,
revision, and retraction. An asynchronous export queue can tolerate publishing
outages without interrupting gameplay. A public story is not canonical game state.

## 7. Shared modules before shared mutable worlds

### Initial platform content model

A central directory offers versioned, validated user-generated adventures,
locations, creatures, and settings. Each campaign instantiates its own copy and
evolves independently. Pin content versions; author updates must not silently
rewrite running campaigns.

The catalog requires provenance, attribution/licensing, moderation, validation,
and treatment of authored material as untrusted input, including instructions
that could influence AI workflows. Importing content must not execute arbitrary
code or override mechanical/security authority.

### Later connected-world experiments

Sharing mutable consequences across groups is a separate research/design step:

- Who owns the authoritative shared-world state?
- How are conflicting actions and timelines resolved?
- Which consequences become public canon, and who approves them?
- Can characters, inventory, or achievements move between campaigns?
- How are griefing, rollback, moderation, and group consent handled?

Begin with bounded opt-in links or approved world events, if pursued at all.
Do not promise one seamless shared universe merely because campaigns share a
module catalog or a publishing channel.

## 8. Boundaries v2 can preserve without expanding its scope

- Keep Python authoritative and browser clients thin.
- Keep public transport replaceable behind a stable gameplay contract.
- Separate player capabilities from facilitator and operational authority.
- Avoid new browser-visible local filesystem or fixed-host assumptions.
- Keep canonical state ownership and persistence boundaries explicit.
- Distinguish authored module content, mutable campaign state, and public stories.
- Preserve useful extension seams rather than introducing speculative services.

These are design considerations when choosing between otherwise suitable v2
approaches. They do not justify a general multi-campaign rewrite, extra release
gates, or delaying the stable internet gameplay build.

## 9. Possible later progression

1. Stable v2 game server, React clients, TITAN, mapping/movement, and world memory.
2. One hosted persistent campaign with a secured remote facilitator interface.
3. A measured fleet of isolated campaigns with identities, invitations, quotas,
   and operational supervision.
4. Community discovery, approved journal publishing, and a shared module catalog.
5. Optional experiments in connected worlds and cross-campaign consequences.

This is an exploratory sequence, not scheduled phases, OpenSpec tasks, approved
infrastructure, or a `/goal`. Major decisions remain open: hosting economics,
identity, storage isolation, moderation, publishing stack, world semantics, and
whether a shared universe proves desirable in actual play.

The next decision point is after stable v2 and further owner review, at least a
year beyond this initial vision discussion. Until then, retain this outline as
directional context only.
