#!/bin/bash
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

set -euo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
image='python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f'
run_id="${1:-$(date -u +%Y%m%dt%H%M%Sz)}"
docker_platform="${2:-linux/arm64}"

if (( $# > 2 )); then
    printf '%s\n' 'Usage: run_linux_leg.sh [run-id] [linux/arm64|linux/amd64]' >&2
    exit 2
fi

if [[ ! "$run_id" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]]; then
    printf '%s\n' 'FAIL: run-id must be 1-32 lowercase letters, digits, or hyphens, starting with a lowercase letter or digit' >&2
    exit 2
fi

if [[ "$docker_platform" != 'linux/arm64' && "$docker_platform" != 'linux/amd64' ]]; then
    printf '%s\n' 'FAIL: platform must be linux/arm64 or linux/amd64' >&2
    exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
    printf '%s\n' 'FAIL: Docker is not available; run this owner script on the host with Docker installed' >&2
    exit 2
fi

if ! build_sha="$(git -C "$repo_root" rev-parse --verify HEAD 2>/dev/null)" \
    || [[ ! "$build_sha" =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]]; then
    printf '%s\n' 'FAIL: could not obtain a valid host Git build identity' >&2
    exit 2
fi

if ! worktree_status="$(git -C "$repo_root" status --porcelain 2>/dev/null)"; then
    printf '%s\n' 'FAIL: could not obtain host worktree status for build identity' >&2
    exit 2
fi
if [[ -n "$worktree_status" ]]; then
    worktree_dirty=1
else
    worktree_dirty=0
fi

if ! host_uid="$(id -u)" || ! host_gid="$(id -g)" \
    || [[ ! "$host_uid" =~ ^[0-9]+$ || ! "$host_gid" =~ ^[0-9]+$ ]]; then
    printf '%s\n' 'FAIL: could not determine numeric host UID/GID for the isolated run mount' >&2
    exit 2
fi

run_root="$repo_root/tmp/n0/linux-leg/$run_id"
evidence_parent="$repo_root/tmp/router-rollout/v2-network"
evidence_dir="$evidence_parent/n0-linux-$run_id"

if [[ -e "$run_root" || -e "$evidence_dir" ]]; then
    printf '%s\n' 'FAIL: run-id already has scratch or evidence; choose a new run-id' >&2
    exit 2
fi

mkdir -p "$repo_root/tmp/n0/linux-leg" "$evidence_parent"
mkdir -m 700 "$run_root"
mkdir -m 700 "$run_root/n0"
printf 'sha=%s\ndirty=%s\n' "$build_sha" "$worktree_dirty" \
    > "$run_root/n0/build-identity.txt"
chmod 600 "$run_root/n0/build-identity.txt"

set +e
docker run --rm --init \
    --name "neq-n0-linux-$run_id" \
    --pull=missing \
    --platform "$docker_platform" \
    --network bridge \
    --read-only \
    --cap-drop=ALL \
    --security-opt=no-new-privileges:true \
    --pids-limit=128 \
    --memory=2g \
    --cpus=2 \
    --user "$host_uid:$host_gid" \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777 \
    --tmpfs "/run/n0:rw,nosuid,nodev,noexec,size=1m,mode=0700,uid=$host_uid,gid=$host_gid" \
    --mount "type=bind,source=$repo_root/scripts/network_spike,target=/workspace/scripts/network_spike,readonly" \
    --mount "type=bind,source=$run_root,target=/workspace/tmp" \
    --env "N0_RUN_ID=$run_id" \
    --env HOME=/workspace/tmp/n0/home \
    --workdir /workspace \
    "$image" \
    /bin/sh -ec '
        mkdir -p /workspace/tmp/n0/home /workspace/tmp/n0/pip-cache
        python3 -m venv /workspace/tmp/n0/.venv
        PIP_CACHE_DIR=/workspace/tmp/n0/pip-cache \
            /workspace/tmp/n0/.venv/bin/python -m pip install \
                --disable-pip-version-check --no-input \
                -r /workspace/scripts/network_spike/requirements-spike.txt
        exec /workspace/tmp/n0/.venv/bin/python \
            /workspace/scripts/network_spike/n0_driver.py \
            --platform linux --run-id "$N0_RUN_ID" \
            --runtime-parent /run/n0
    '
docker_status=$?
set -e

container_evidence_dir="$run_root/router-rollout/v2-network/n0-linux-$run_id"
if [[ -d "$container_evidence_dir" ]]; then
    if [[ -e "$evidence_dir" ]]; then
        printf 'FAIL: refusing to overwrite evidence: %s\n' "$evidence_dir" >&2
        exit 2
    fi
    mv "$container_evidence_dir" "$evidence_dir"
    printf 'Evidence: %s\n' "${evidence_dir#"$repo_root/"}"
else
    printf 'No evidence directory was produced. Scratch retained at %s\n' \
        "${run_root#"$repo_root/"}" >&2
fi

if [[ -d "$evidence_dir" ]]; then
    postcheck_dir="$evidence_dir"
else
    postcheck_dir="$run_root"
fi
mkdir -p "$postcheck_dir"
postcheck_file="$postcheck_dir/host-postcheck.txt"
{
    printf 'docker_run_exit_status=%s\n' "$docker_status"
    printf 'docker ps -a container IDs (expected empty):\n'
    docker ps -a \
        --filter "name=^neq-n0-linux-${run_id}$" \
        --format '{{.ID}}' 2>&1 || printf 'docker_ps_exit_status=%s\n' "$?"
    printf 'docker image inspect RepoDigests:\n'
    docker image inspect --format '{{json .RepoDigests}}' "$image" 2>&1 \
        || printf 'docker_image_inspect_exit_status=%s\n' "$?"
    printf 'uname -a:\n'
    uname -a 2>&1 || printf 'uname_exit_status=%s\n' "$?"
    printf 'date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ:\n'
    date -u +%Y-%m-%dT%H:%M:%SZ 2>&1 || printf 'date_exit_status=%s\n' "$?"
} > "$postcheck_file"

exit "$docker_status"
