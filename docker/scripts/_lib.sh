#!/usr/bin/env bash
# Shared helpers for scripts under docker/scripts. Not user-facing — source it
# from another script in this directory:
#     source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
#
# Exports absolute paths: DOCKER_DIR, REPO_ROOT.
# Provides functions (ezbeq::* namespace) for preflight checks, env loading,
# config resolution, git metadata, and GHCR owner detection.

# Derive paths from this file's location, independent of caller's CWD.
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$_LIB_DIR/.." && pwd)"
REPO_ROOT="$(cd "$DOCKER_DIR/.." && pwd)"

# Capture the caller's script path at source-time so print_help works even
# after the caller cd's elsewhere. BASH_SOURCE[1] is the sourcing script;
# this only resolves correctly at top-level of _lib.sh, so we do it here.
_CALLER_PATH="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)/$(basename "${BASH_SOURCE[1]}")"

# Emit a header comment block from the caller script as usage output.
# $1/$2 = optional start/end line numbers (default 2..24 — skip shebang,
# catch the top comment block). macOS-safe sed (-E).
ezbeq::print_help() {
    local start="${1:-2}" end="${2:-24}"
    sed -n "${start},${end}p" "$_CALLER_PATH" | sed -E 's/^# ?//'
}

ezbeq::require_docker() {
    command -v docker >/dev/null 2>&1 || {
        echo "Error: docker CLI not found in PATH." >&2
        exit 1
    }
}

ezbeq::require_compose() {
    docker compose version >/dev/null 2>&1 || {
        echo "Error: docker compose v2 plugin not available." >&2
        echo "       Install Docker Desktop or the docker-compose-plugin package." >&2
        exit 1
    }
}

ezbeq::require_buildx() {
    docker buildx version >/dev/null 2>&1 || {
        echo "Error: docker buildx not available." >&2
        echo "       Install Docker Desktop or the buildx plugin:" >&2
        echo "       https://docs.docker.com/build/install-buildx/" >&2
        exit 1
    }
}

# Load docker/.env into the environment if present.
ezbeq::load_env() {
    local env_file="$DOCKER_DIR/.env"
    if [[ -f "$env_file" ]]; then
        set -o allexport
        # shellcheck disable=SC1090
        source "$env_file"
        set +o allexport
    fi
}

# Resolve EZBEQ_CONFIG (env var or ~/.ezbeq/ezbeq.yml default), fail if the
# file is missing, auto-detect EZBEQ_PORT from its `port:` key if unset.
# Exports EZBEQ_CONFIG_HOME and EZBEQ_PORT for docker-compose interpolation.
ezbeq::resolve_config() {
    EZBEQ_CONFIG="${EZBEQ_CONFIG:-$HOME/.ezbeq/ezbeq.yml}"
    if [[ ! -f "$EZBEQ_CONFIG" ]]; then
        echo "Error: ezbeq.yml not found at $EZBEQ_CONFIG" >&2
        echo "       Create it, or set EZBEQ_CONFIG to its path in docker/.env." >&2
        exit 1
    fi
    if [[ -z "${EZBEQ_PORT:-}" ]]; then
        EZBEQ_PORT=$(grep -E '^\s*port\s*:' "$EZBEQ_CONFIG" 2>/dev/null | head -1 \
            | sed 's/[^:]*:[[:space:]]*//' | tr -d ' \r\n')
        EZBEQ_PORT="${EZBEQ_PORT:-8080}"
    fi
    export EZBEQ_CONFIG_HOME="$(dirname "$EZBEQ_CONFIG")"
    export EZBEQ_PORT
}

# Populate GIT_BRANCH and GIT_SHA from the repo at REPO_ROOT. Silent empty
# strings if git is unavailable or the directory isn't a repo.
ezbeq::resolve_git_info() {
    GIT_BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    GIT_SHA=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "")
}

# Resolve the GHCR owner: OWNER env var wins, else parse from the `origin`
# remote URL. Exits with a clear error if neither works.
ezbeq::resolve_owner() {
    if [[ -z "${OWNER:-}" ]]; then
        local origin
        origin=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)
        OWNER=$(echo "$origin" | sed -nE 's#.*[:/]([^/]+)/ezbeq(\.git)?$#\1#p')
        if [[ -z "$OWNER" ]]; then
            echo "Error: could not determine GHCR owner from origin remote." >&2
            echo "       origin url: ${origin:-<unset>}" >&2
            echo "       Set OWNER=<github-user-or-org> and rerun." >&2
            exit 1
        fi
    fi
}
