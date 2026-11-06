// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { execFileSync } from "node:child_process";

export function readWorkspaceIdentity(repositoryRoot, run = execFileSync) {
  let gitSha = "unknown";
  let worktreeState = "unknown";
  try {
    const value = run("git", ["rev-parse", "HEAD"], {
      cwd: repositoryRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    if (/^[a-f0-9]{40,64}$/i.test(value)) gitSha = value;
  } catch {
    // Keep unknown identity fail-closed; the owner-run driver refuses it.
  }
  try {
    const porcelain = run("git", ["status", "--porcelain"], {
      cwd: repositoryRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    worktreeState = porcelain.trim() === "" ? "clean" : "dirty";
  } catch {
    // A status failure is not evidence of a clean worktree.
  }
  return {
    git_sha: gitSha,
    git_worktree_state: worktreeState,
    git_worktree_clean: worktreeState === "clean",
  };
}
