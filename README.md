# NeverEndingQuest-TTRPG

<img src="dm_logo.png" alt="NeverEndingQuest DM Logo" width="96" align="left" style="margin-right: 16px;">

**Tabletop-focused fork of [NeverEndingQuest](https://github.com/MoonlightByte/NeverEndingQuest)** for local, in-person facilitator-led multiplayer sessions.

An AI-powered Dungeon Master for SRD 5.2.1 compatible tabletop RPG campaigns — designed for a single laptop with a facilitator managing multiple player characters through a tabbed web UI.

<br clear="left">

---

## Quick Start

### One-Click Installers

| Platform | Installer |
|----------|-----------|
| **Windows** | [install_neverendingquest_windows.bat](https://github.com/zeug-zz/NeverEndingQuest-TTRPG/raw/main/install_neverendingquest_windows.bat) — Right-click → Save Link As → double-click |
| **macOS** | [install_neverendingquest_macos.sh](https://github.com/zeug-zz/NeverEndingQuest-TTRPG/raw/main/install_neverendingquest_macos.sh) — Save to Downloads, then `bash ~/Downloads/install_neverendingquest_macos.sh` |

Installers handle Python, Git, virtual environment, dependencies, config, and desktop launcher creation.

### Manual Setup

```bash
git clone https://github.com/zeug-zz/NeverEndingQuest-TTRPG.git
cd NeverEndingQuest-TTRPG
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config_template.py config.py     # Add your OpenAI API key
.venv/bin/python run_web.py          # Opens http://localhost:8357
```

### Alternative Launch

- **Module Toolkit**: `.venv/bin/python launch_toolkit.py`
- **Terminal mode**: `.venv/bin/python main.py` (limited features)

---

## What This Fork Adds (Tabletop Mode)

Built as a merge-safe plugin on top of upstream. Tabletop Mode activates automatically when `partyMembers` in `party_tracker.json` has more than one entry.

- **Tabbed Multi-PC UI** — Switch between character sheets in the web interface. Each PC gets their own tab with stats, inventory, and portrait.
- **Deterministic Multi-PC Combat** — Turn queue with initiative tracking, PC phase / enemy phase automation, and `/end` batch resolution. Enemy HP and status changes use structured ops with fail-open prose fallback.
- **PC Lifecycle Management** — Create, edit, promote (NPC→PC), retire, and return characters with world-memory continuity via `data/memory.db`.
- **Party & NPC State Sync** — Deterministic arrival validation, travel reconciliation, companion relationship edges, and scene-follower persistence.
- **Module Publication Pipeline** — Ingest, validate, enrich, and publish homebrew modules with readiness/publishability gating and semantic authority auditing.

All fork modifications are marked with `# TABLETOP MODE:` comments and live in extension files where possible. See `AGENTS.md` for architecture, conventions, and the complete change log.

---

## Included Adventure Modules

| Module | Level | Description |
|--------|-------|-------------|
| **The Thornwood Watch** | 1–2 | Defend a ranger outpost from bandits and corruption |
| **Keep of Doom** | 3–5 | Explore a haunted keep and establish your stronghold |
| **The Pumpkin King's Curse** | 1–3 | Unravel a harvest-time folk-horror curse across Greenfields Vale |
| **Night of the Restless Dead** | 1–2 | Investigate undead outbreaks beneath a ruined cathedral |
| **Garden of Demons** | 1–3 | Navigate a fey-touched garden of dangerous whimsy |
| **Murder at the Drowning Lass** | 1–3 | Solve a tavern murder mystery with branching investigation |
| **The Hidden City of Numillian** | 3–5 | Discover a subterranean city of paradox and lost knowledge |

Modules connect through a hub-and-spoke world model. Cross-module continuity is maintained through living summaries, companion memory, and persistent world state.

---

## Module Toolkit

Create, edit, and publish adventure modules from the web interface:

- **Module Builder** — AI-assisted or manual module creation with area, plot, NPC, and monster generation
- **NPC & Monster Generators** — Generate stat blocks, backstories, and portraits
- **Module Media Generator** — Batch image generation for module NPCs and monsters
- **Homebrew Ingest** — Import community adventures (Homebrewery markdown, PDF) with validation and semantic enrichment
- **Graphic Pack System** — Reusable/shareable visual asset packs

---

## Documentation

- **Engineering conventions & change log**: `AGENTS.md`
- **Architecture & development**: `docs/development/`
- **Architecture decisions**: `adrs/`
- **Active implementation contracts**: `openspec/changes/`
- **Long-horizon planning**: `plans/`
- **Contributing**: `CONTRIBUTING.md`, `DEV_SETUP.md`

---

## Project Structure

```
core/          AI integration, generators, managers, validation, toolkit
utils/         Utilities, compression, state sync guards
updates/       Character, encounter, and save state mutation
web/           Flask server, SocketIO handlers, routes, templates, static
modules/       Adventure modules (areas, characters, monsters, encounters, plots)
prompts/       AI system prompts and validation contracts
schemas/       JSON validation schemas
data/          Bestiary, memory DB, runtime state
graphic_packs/ Reusable visual asset packs
scripts/       Validation, auditing, remediation, and testing scripts
```

---

## License

NeverEndingQuest is licensed under the **Fair Source License 1.0** with a 5-year transition to Apache 2.0. Free for personal, educational, and non-commercial use.

Game mechanics use SRD 5.2.1 content from Wizards of the Coast (CC BY 4.0). This is unofficial Fan Content not affiliated with or endorsed by Wizards of the Coast.

See `LICENSE` and `LICENSING.md` for full terms.

---

**Upstream**: [MoonlightByte/NeverEndingQuest](https://github.com/MoonlightByte/NeverEndingQuest) | **Fork**: [zeug-zz/NeverEndingQuest-TTRPG](https://github.com/zeug-zz/NeverEndingQuest-TTRPG)
