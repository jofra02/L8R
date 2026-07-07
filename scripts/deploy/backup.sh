#!/usr/bin/env bash
# Full production backup: PostgreSQL dump + Qdrant snapshots (downloaded) +
# gateway inventory/.env secrets tar + optional evidence blobs.
#
# Usage:
#   bash scripts/deploy/backup.sh [--no-evidence] [--keep N] [--label <str>]
#
# Output contract: informational messages go to stderr; the ONLY stdout line
# is the created backup directory path (so callers can capture it):
#   BACKUP_DIR=$(bash scripts/deploy/backup.sh | tail -n1)
#
# Respects COMPOSE_PROJECT_NAME and the compose port variables from the
# environment; falls back to .env, then to compose defaults.
# See docs/operations/backup_restore.md for the restore procedure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

KEEP=5
WITH_EVIDENCE=1
LABEL=""

while [ $# -gt 0 ]; do
    case "$1" in
        --no-evidence) WITH_EVIDENCE=0; shift ;;
        --keep) KEEP="$2"; shift 2 ;;
        --label) LABEL="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,14p' "${BASH_SOURCE[0]}" >&2
            exit 0 ;;
        *) echo "Unknown flag: $1" >&2; exit 2 ;;
    esac
done

log()  { echo "[backup] $*" >&2; }
fail() { echo "[backup] ERROR: $*" >&2; exit 1; }

# getcfg KEY DEFAULT — shell environment wins, then .env, then default.
# Never `source .env` wholesale: values may contain JSON/spaces.
getcfg() {
    local key="$1" def="$2" val=""
    val="$(eval "printf '%s' \"\${$key:-}\"")"
    if [ -z "$val" ] && [ -f "$REPO_ROOT/.env" ]; then
        val="$(grep -E "^${key}=" "$REPO_ROOT/.env" | head -n1 | cut -d= -f2- || true)"
        val="${val%$'\r'}"
        # Strip trailing inline comment (whitespace + #) and surrounding spaces
        val="$(printf '%s' "$val" | sed -e 's/[[:space:]]\{1,\}#.*$//' -e 's/[[:space:]]*$//')"
    fi
    printf '%s' "${val:-$def}"
}

DB_USER="$(getcfg DB_USER postgres)"
DB_NAME="$(getcfg DB_NAME support_agent_db)"
QDRANT_PORT="$(getcfg QDRANT_PORT 6333)"
QDRANT_BASE="http://localhost:${QDRANT_PORT}"

preflight() {
    local cmd
    for cmd in docker curl tar git; do
        command -v "$cmd" >/dev/null || fail "required command not found: $cmd"
    done
    docker compose version >/dev/null 2>&1 || fail "docker compose is not available"

    local running
    running="$(docker compose ps --services --status running 2>/dev/null || true)"
    echo "$running" | grep -qx postgres || fail "postgres container is not running"
    echo "$running" | grep -qx qdrant   || fail "qdrant container is not running"

    # Warn (do not fail) below ~2 GB free on the repo filesystem
    local avail_kb
    avail_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')"
    if [ "${avail_kb:-0}" -lt 2097152 ]; then
        log "WARNING: less than 2 GB free on this filesystem (${avail_kb} KB)"
    fi
}

make_backup_dir() {
    local stamp sha suffix=""
    stamp="$(date -u +%Y%m%d-%H%M%S)"
    sha="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
    [ -n "$LABEL" ] && suffix="_${LABEL}"
    BACKUP_DIR="$REPO_ROOT/backups/${stamp}_${sha}${suffix}"
    mkdir -p "$BACKUP_DIR/qdrant"
    chmod 700 "$BACKUP_DIR" 2>/dev/null || true
    log "backup dir: $BACKUP_DIR"
}

backup_postgres() {
    log "dumping PostgreSQL ($DB_NAME as $DB_USER)..."
    docker compose exec -T postgres pg_dump -U "$DB_USER" -Fc "$DB_NAME" \
        > "$BACKUP_DIR/postgres_${DB_NAME}.dump"
    [ -s "$BACKUP_DIR/postgres_${DB_NAME}.dump" ] || fail "pg_dump produced an empty file"
    log "postgres dump: $(du -h "$BACKUP_DIR/postgres_${DB_NAME}.dump" | cut -f1)"
}

backup_qdrant() {
    log "snapshotting Qdrant collections via $QDRANT_BASE ..."
    local collections c snap
    collections="$(curl -sf "$QDRANT_BASE/collections" \
        | grep -o '"name":"[^"]*"' | cut -d'"' -f4 || true)"
    if [ -z "$collections" ]; then
        log "WARNING: no Qdrant collections found; skipping"
        return 0
    fi
    for c in $collections; do
        log "  snapshot: $c"
        snap="$(curl -sf -X POST "$QDRANT_BASE/collections/$c/snapshots" \
            | grep -o '"name":"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
        [ -n "$snap" ] || fail "snapshot creation failed for collection '$c'"
        # Download to make the backup portable (a snapshot left inside the
        # qdrant_data volume is lost together with the volume), then delete
        # the server-side copy to keep the volume lean.
        curl -sf "$QDRANT_BASE/collections/$c/snapshots/$snap" \
            -o "$BACKUP_DIR/qdrant/$c.snapshot" \
            || fail "snapshot download failed for '$c'"
        curl -sf -X DELETE "$QDRANT_BASE/collections/$c/snapshots/$snap" >/dev/null \
            || log "WARNING: could not delete server-side snapshot $c/$snap"
    done
}

backup_secrets() {
    log "archiving secrets (gateway inventory + .env)..."
    local members=("mcp_gateway/inventory")
    [ -f "$REPO_ROOT/.env" ] && members+=(".env")
    [ -f "$REPO_ROOT/mcp_gateway/.env" ] && members+=("mcp_gateway/.env")
    tar czf "$BACKUP_DIR/inventory_and_env.tgz" -C "$REPO_ROOT" "${members[@]}"
    chmod 600 "$BACKUP_DIR/inventory_and_env.tgz" 2>/dev/null || true
    log "WARNING: inventory_and_env.tgz contains INVENTORY_MASTER_KEY and all"
    log "         platform secrets. Store it off-server in a secure location."
}

backup_evidence() {
    if [ "$WITH_EVIDENCE" -ne 1 ]; then
        log "skipping evidence blobs (--no-evidence)"
        return 0
    fi
    if ! docker compose ps --services --status running 2>/dev/null | grep -qx app; then
        log "WARNING: app container not running; skipping evidence blobs"
        return 0
    fi
    log "archiving evidence blobs (evidence_data volume, via app container)..."
    # sh -c keeps the container-side /app path out of the host argv (Git Bash
    # would otherwise rewrite leading-slash arguments to Windows paths)
    docker compose exec -T app sh -c 'tar czf - -C /app data/evidence' \
        > "$BACKUP_DIR/evidence.tgz"
}

write_manifest() {
    local env_sha="n/a"
    [ -f "$REPO_ROOT/.env" ] && env_sha="$(sha256sum "$REPO_ROOT/.env" | cut -d' ' -f1)"
    {
        echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "git_sha=$(git rev-parse HEAD 2>/dev/null || echo n/a)"
        echo "git_ref=$(git symbolic-ref --short -q HEAD || git rev-parse HEAD 2>/dev/null || echo n/a)"
        echo "label=${LABEL:-none}"
        echo "env_sha256=$env_sha"
        echo "compose_project=${COMPOSE_PROJECT_NAME:-default}"
        echo "images:"
        docker compose images 2>/dev/null | sed 's/^/  /' || true
        echo "contents:"
        (cd "$BACKUP_DIR" && find . -type f ! -name manifest.txt | sed 's/^/  /')
    } > "$BACKUP_DIR/manifest.txt"
}

prune_old_backups() {
    # Keep the newest $KEEP timestamped backup dirs; names sort chronologically.
    local dirs count=0 d
    dirs="$(cd "$REPO_ROOT/backups" 2>/dev/null \
        && ls -1d [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]_* 2>/dev/null \
        | sort -r || true)"
    [ -n "$dirs" ] || return 0
    while IFS= read -r d; do
        count=$((count + 1))
        if [ "$count" -gt "$KEEP" ]; then
            log "pruning old backup: backups/$d"
            rm -rf "${REPO_ROOT:?}/backups/$d"
        fi
    done <<< "$dirs"
}

preflight
make_backup_dir
backup_postgres
backup_qdrant
backup_secrets
backup_evidence
write_manifest
prune_old_backups

log "backup complete."
echo "$BACKUP_DIR"
