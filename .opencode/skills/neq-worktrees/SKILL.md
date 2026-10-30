---
name: neq-worktrees
description: Safely isolate, validate, review, integrate, and clean up substantial NeverEndingQuest work in OpenCode or Git worktrees. Never move an active goal or dirty work into a new worktree without explicit direction.
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: isolated-development-and-integration
  project: NeverEndingQuest
---

# NeverEndingQuest Worktree Workflow

Use this skill when the user asks to use/manage a worktree, or before a substantial independent implementation where isolation would help. A worktree isolates committed Git history and files; it does not carry over uncommitted changes or isolate databases, credentials, ports, or other external state.

The goal is a small, reviewable change integrated through this repository's normal PR process. Creating a worktree is not permission to commit, push, merge, discard changes, or delete a branch.

## Non-negotiable safety rules

- **Do not interrupt an active goal/build.** If this is continuing an OpenSpec change, long-running goal, or implementation already underway in the current checkout, keep working in that checkout. Do not create a worktree or move the session unless the user explicitly asks to isolate that same work and confirms how its current changes should be handled.
- **Never strand dirty work.** A new worktree starts from a commit; staged, unstaged, untracked, and ignored files do not transfer. Do not stash, copy, commit, reset, switch branches, or otherwise move existing work to make a worktree convenient. Explain the limitation and ask the user whether to continue in place or choose a clean, specific committed base.
- **Ask before creating a worktree** unless the user's current instruction explicitly authorizes it. Do not infer permission from repository size, parallelism, or this skill being loaded.
- Prefer OpenCode's native worktree and session tools when available. Read their current tool descriptions and use them; do not also run `git worktree` for a worktree OpenCode manages. Use manual Git worktrees only if native tools are unavailable and the user approves that fallback.
- Never force-remove a worktree, discard uncommitted work, force-push, or delete a branch. Cleanup and integration are separate actions and require user approval.
- Never merge from or push to the historical `upstream` remote. Push to `origin` explicitly only after approval.
- The repository documents `main` as PR-protected, requiring a PR and linear history. Do not integrate by committing or merging directly on `main`; use the fork's PR workflow.

## 1. Establish the task and current workspace

1. Confirm this is a new, independent task rather than a continuation of active work. Read the repository `AGENTS.md` and the applicable active OpenSpec change before implementation. Preserve its task scope and verification requirements.
2. Announce: `Using the neq-worktrees workflow. I will preserve existing changes and ask before creating, integrating, or removing a worktree.`
3. Use read-only checks to establish the repository root, current branch, worktree state, and dirty files:

   ```bash
   git rev-parse --show-toplevel
   git rev-parse --git-dir
   git rev-parse --git-common-dir
   git rev-parse --show-superproject-working-tree
   git branch --show-current
   git status --short --branch
   git worktree list --porcelain
   ```

   A submodule can also have different Git and common directories; check the superproject result before calling the checkout a linked worktree. If already in a linked worktree, reuse it; do not nest another one.
4. If the current checkout has changes, report that they will not be present in a new worktree. If those changes belong to this task or an active goal, stay in place. If the intended base is unclear, stop and ask; do not guess between local `main`, `origin/main`, or another branch. Never use `upstream` as a base for routine fork work.
5. Check the intended base explicitly. A local `main` that is ahead of or diverged from the known `origin/main` is not an automatic worktree base. Do not fetch, rebase, reset, or reconcile branches to hide the difference; explain it and ask which committed base the user intends. A fetch from `origin` may refresh remote-tracking information only when useful, but it does not authorize integration or pushing.

## 2. Create and enter the worktree

1. Propose a descriptive branch/worktree name using the repository's `feature/`, `fix/`, or `chore/` convention. State the intended committed base and what existing work will remain untouched. Get user approval if it was not already explicit.
2. Use the native OpenCode worktree creation tool. Confirm the returned directory and resulting branch/base before doing destination-dependent work. If the tool cannot select or establish the intended base, stop and ask rather than silently using a different commit.
3. Move the session into the new directory only for a newly authorized task, and only after confirming that moving this session will not interrupt an active goal or detach dirty work. Use OpenCode's session-move tool if available; continue destination-dependent work only after the move takes effect.
4. Verify the new root, branch, and status. If Git reports an unexpected branch, unexpected modifications, or the wrong repository, stop without changing anything.
5. Keep the default to **one active feature worktree**. Use more only when the user requests parallel independent tasks and their bases, ports, and test data can be kept separate.

## 3. Set up and validate safely

- Follow `DEV_SETUP.md` and `AGENTS.md`; use `.venv/bin/python` for runtime and dependency-sensitive commands. Do not copy or symlink `.venv` from another checkout. If dependencies must be installed in this worktree, report the setup needed and ask before doing an install with side effects.
- Do not copy ignored secrets or user/runtime data into the worktree. This includes `config.py`, campaign and world state, characters, saves, conversation history, and local uploads. Ask the user to provision any required local configuration safely; never print secret values.
- Keep tests focused on the active change's acceptance criteria and relevant regressions. Use the exact validation commands required by its OpenSpec artifacts and `AGENTS.md`; do not claim the whole project passes when only focused checks ran. Record commands and results for review.
- Do not run gameplay/capture tests against the user's installed campaign or port 8357. For an approved live capture, follow `.opencode/skills/neq-capture-arena/SKILL.md` exactly: isolated state, port 8360, and its evidence/teardown rules. Do not run concurrent captures against shared state or port 8360.
- Do not edit the user's unrelated files, generated runtime state, or another worktree. If a check would do so, stop and ask.

## 4. Review and integrate through a PR

Before proposing integration:

1. Inspect `git status --short --branch`, the complete diff, and the changed-file list. Confirm only task-related files are present and no user/runtime data or unrelated edits slipped in.
2. Run `git diff --check` and the task's required focused validation. For OpenSpec work, preserve its artifacts and evidence; do not mark tasks complete solely because implementation in the worktree is done.
3. Compare the feature branch with the intended `origin/main` base and report whether `main` has advanced. Do not silently merge, rebase, cherry-pick, or resolve ambiguous conflicts. If reconciliation is needed, explain the choices and wait for direction; never rewrite shared history or force-push.
4. Present a concise review summary: purpose, changed files, test commands/results, known failures or baseline failures, branch/base, and whether the branch is ready for a PR.
5. Do not commit, push, or open a PR without explicit authorization. If approved, push only the named branch to `origin` (never use a bare `git push`) and target the fork's `main`, never upstream. Follow required PR checks and linear-history rules. A squash PR merge may be suggested when supported, but do not choose or perform a merge method without approval.
6. Stop on conflicts, unexpected divergence, failed required checks, unrelated changes, or unclear ownership. Report the concrete blocker; do not make the diff look clean by dropping work.

## 5. Verify and clean up separately

- After the user confirms the PR was merged, verify the integrated result on the fork's `main` and run any required post-merge checks. Do not assume a successful PR means every local requirement or evidence gate is complete.
- Keep the worktree and branch available for review unless the user separately approves cleanup.
- For approved cleanup, use OpenCode's native worktree removal with force disabled. If removal reports uncommitted changes, stop and show the status; never force-remove them. Delete the feature branch only with separate explicit approval and only after verifying the PR is merged.
- Never automatically commit changes as part of worktree deletion.

## Stop conditions

Stop and ask the user if the task is already in progress in a dirty checkout, the requested base is ambiguous, the worktree/session tools cannot preserve the intended state, setup requires unapproved changes, a conflict has unclear intent, required checks fail, or cleanup would discard any work.

## Attribution

Workflow inspiration adapted for this repository from `obra/superpowers`' `using-git-worktrees` skill:
https://github.com/obra/superpowers/blob/main/skills/using-git-worktrees/SKILL.md

The upstream skill is MIT-licensed.

MIT License

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
