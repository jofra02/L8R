#!/usr/bin/env bash
# Safe production redeploy for the docker compose stack.
#
# Standard usage (on the production server, from the repo root):
#   bash scripts/deploy/redeploy.sh --ref v1.2.3
#   bash scripts/deploy/redeploy.sh                 # git pull --ff-only current branch
#   bash scripts/deploy/redeploy.sh --no-pull       # config-only deploy (working tree as-is)
#   bash scripts/deploy/redeploy.sh --rollback      # revert code to the last backup's SHA
#
# Flags:
#   --ref <tag|branch|sha>     checkout this ref instead of pulling
#   --no-pull                  deploy the working tree as-is (skips fetch/checkout)
#   --skip-backup              skip the pre-deploy backup (discouraged)
#   --services "app frontend"  partial redeploy (space-separated compose services)
#   --allow-name-drift         accept an intentional gateway baseline change
#   --rollback [backup-dir]    roll code back to the SHA recorded in the backup manifest
#   --yes                      non-interactive (skip confirmation prompts)
#
# Sequence: preflight -> backup -> fetch -> build -> name-freeze gate ->
# confirm -> up -d --wait (migrations run in the app entrypoint) -> verify.
# Database rollback is NEVER automatic; see docs/operations/production_redeploy.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

REF=""
NO_PULL=0
SKIP_BACKUP=0
SERVICES=""
ALLOW_NAME_DRIFT=0
ROLLBACK=0
ROLLBACK_DIR=""
ASSUME_YES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --ref) REF="$2"; shift 2 ;;
        --no-pull) NO_PULL=1; shift ;;
        --skip-backup) SKIP_BACKUP=1; shift ;;
        --services) SERVICES="$2"; shift 2 ;;
        --allow-name-drift) ALLOW_NAME_DRIFT=1; shift ;;
        --rollback)
            ROLLBACK=1; shift
            if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then ROLLBACK_DIR="$1"; shift; fi ;;
        --yes) ASSUME_YES=1; shift ;;
        -h|--help)
            sed -n '2,21p' "${BASH_SOURCE[0]}" >&2
            exit 0 ;;
        *) echo "Unknown flag: $1" >&2; exit 2 ;;
    esac
done

PHASE="init"
PREV_REF=""
PREV_SHA=""
NEW_SHA=""
MOVED=0
BACKUP_DIR=""

log()  { echo "[redeploy] $*" >&2; }
fail() { echo "[redeploy] ERROR: $*" >&2; exit 1; }

on_err() {
    echo "[redeploy] FAILED during phase: $PHASE" >&2
    if [ -n "$BACKUP_DIR" ]; then
        echo "[redeploy] Pre-deploy backup: $BACKUP_DIR" >&2
    fi
    echo "[redeploy] To revert code: bash scripts/deploy/redeploy.sh --rollback" >&2
}
trap on_err ERR

# getcfg KEY DEFAULT — shell environment wins, then .env, then default.
getcfg() {
    local key="$1" def="$2" val=""
    val="$(eval "printf '%s' \"\${$key:-}\"")"
    if [ -z "$val" ] && [ -f "$REPO_ROOT/.env" ]; then
        val="$(grep -E "^${key}=" "$REPO_ROOT/.env" | head -n1 | cut -d= -f2- || true)"
        val="${val%$'\r'}"
        val="$(printf '%s' "$val" | sed -e 's/[[:space:]]\{1,\}#.*$//' -e 's/[[:space:]]*$//')"
    fi
    printf '%s' "${val:-$def}"
}

gateway_in_scope() {
    [ -z "$SERVICES" ] && return 0
    case " $SERVICES " in *" mcp-gateway "*) return 0 ;; *) return 1 ;; esac
}

preflight() {
    PHASE="preflight"
    log "preflight checks..."
    local cmd
    for cmd in git docker curl tar; do
        command -v "$cmd" >/dev/null || fail "required command not found: $cmd"
    done
    docker compose version >/dev/null 2>&1 || fail "docker compose is not available"
    [ -f "$REPO_ROOT/.env" ] || fail ".env not found — configure the environment first (docs/setup/deployment.md)"

    local running
    running="$(docker compose ps --services --status running 2>/dev/null || true)"
    if [ -z "$running" ]; then
        log "WARNING: no stack is currently running. For a first install follow docs/setup/deployment.md."
    fi

    if [ "$NO_PULL" -ne 1 ] && [ -n "$(git status --porcelain)" ]; then
        fail "working tree is dirty; commit/stash changes or use --no-pull"
    fi
    PREV_REF="$(git symbolic-ref --short -q HEAD || git rev-parse HEAD)"
    PREV_SHA="$(git rev-parse HEAD)"

    # .env sanity: refuse known placeholders, warn on risky-but-valid configs
    [ "$(getcfg DB_PASS '')" != "change_me" ] || fail "DB_PASS is still the placeholder 'change_me'"
    local jwt
    jwt="$(getcfg JWT_SECRET_KEY '')"
    # Empty falls back to the in-code default, which IS the placeholder
    { [ -n "$jwt" ] && [ "$jwt" != "CHANGE-ME-IN-PRODUCTION" ]; } || fail "JWT_SECRET_KEY is empty or still the placeholder"
    local key
    key="$(getcfg OPENAI_API_KEY '')"
    { [ -n "$key" ] && [ "$key" != "sk-..." ]; } || fail "OPENAI_API_KEY is not configured"
    [ -n "$(getcfg GATEWAY_ADMIN_TOKEN '')" ]   || log "WARNING: GATEWAY_ADMIN_TOKEN empty — gateway admin API and inventory sync are disabled"
    [ -n "$(getcfg INVENTORY_MASTER_KEY '')" ]  || log "WARNING: INVENTORY_MASTER_KEY empty — encrypted device tokens cannot be decrypted"

    # The gateway container runs as uid 1000 (appuser) and provisions tenants by
    # writing to the ./mcp_gateway/inventory bind mount. A repo cloned as root
    # leaves it root-owned -> admin API answers 500 EACCES on the first write.
    local inv_dir="$REPO_ROOT/mcp_gateway/inventory/tenants"
    if [ -d "$inv_dir" ]; then
        local inv_writable=1
        if docker compose ps --services --status running 2>/dev/null | grep -qx mcp-gateway; then
            docker compose exec -T mcp-gateway sh -c 'test -w /app/inventory/tenants' >/dev/null 2>&1 || inv_writable=0
        else
            [ "$(stat -c %u "$inv_dir" 2>/dev/null || echo '')" = "1000" ] || inv_writable=0
        fi
        if [ "$inv_writable" -ne 1 ]; then
            log "WARNING: mcp_gateway/inventory is not writable by the gateway container (uid 1000)."
            log "WARNING: tenant/device provisioning will fail with 'HTTP 500: Permission denied'."
            log "WARNING: fix: chown -R 1000:1000 $REPO_ROOT/mcp_gateway/inventory"
        fi
    fi
    [ "$(getcfg APP_ENV development)" = "production" ] || log "WARNING: APP_ENV is not 'production'"
    # Only relevant when the tunnel profile is active (cloudflared in scope)
    if docker compose config --services 2>/dev/null | grep -qx cloudflared; then
        [ -n "$(getcfg CLOUDFLARE_TUNNEL_TOKEN '')" ] || log "WARNING: tunnel profile active but CLOUDFLARE_TUNNEL_TOKEN empty — cloudflared will crash-loop"
    fi

    local avail_kb
    avail_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')"
    if [ "${avail_kb:-0}" -lt 2097152 ]; then
        log "WARNING: less than 2 GB free on this filesystem (${avail_kb} KB)"
    fi
}

do_backup() {
    PHASE="backup"
    if [ "$SKIP_BACKUP" -eq 1 ]; then
        log "WARNING: --skip-backup: no pre-deploy backup will be taken."
        log "WARNING: a failed migration would leave you with NO safe database rollback."
        if [ "$ASSUME_YES" -ne 1 ]; then
            printf "[redeploy] Type YES to continue without a backup: " >&2
            local answer; read -r answer
            [ "$answer" = "YES" ] || fail "aborted"
        fi
        return 0
    fi
    log "taking pre-deploy backup..."
    BACKUP_DIR="$(bash "$SCRIPT_DIR/backup.sh" --label predeploy | tail -n1)"
    [ -d "$BACKUP_DIR" ] || fail "backup did not produce a directory"
    {
        echo "deploy_prev_ref=$PREV_REF"
        echo "deploy_prev_sha=$PREV_SHA"
        echo "deploy_target_ref=${REF:-pull}"
    } >> "$BACKUP_DIR/manifest.txt"
    log "backup stored at: $BACKUP_DIR"
}

fetch_code() {
    PHASE="fetch_code"
    if [ "$NO_PULL" -eq 1 ]; then
        NEW_SHA="$PREV_SHA"
        log "--no-pull: deploying working tree as-is ($(git rev-parse --short HEAD))"
        return 0
    fi
    log "fetching code..."
    git fetch --tags origin
    if [ -n "$REF" ]; then
        git checkout --detach "$REF"
        MOVED=1
    else
        git pull --ff-only
    fi
    NEW_SHA="$(git rev-parse HEAD)"
    if [ "$NEW_SHA" = "$PREV_SHA" ]; then
        log "no code change ($NEW_SHA); continuing (config/.env may still have changed)"
    else
        log "code: $PREV_SHA -> $NEW_SHA"
    fi
}

restore_prev_code() {
    if [ "$MOVED" -eq 1 ] || [ "${NEW_SHA:-$PREV_SHA}" != "$PREV_SHA" ]; then
        log "restoring previous code: $PREV_REF"
        git checkout "$PREV_REF" >&2 || log "WARNING: could not restore $PREV_REF automatically"
    fi
}

build_images() {
    PHASE="build_images"
    log "building images (running stack untouched)..."
    # shellcheck disable=SC2086
    if ! docker compose build $SERVICES; then
        restore_prev_code
        fail "image build failed; production was not modified"
    fi
}

name_freeze_gate() {
    PHASE="name_freeze_gate"
    if ! gateway_in_scope; then
        log "name-freeze gate skipped (mcp-gateway not in --services scope)"
        return 0
    fi
    if [ "$ALLOW_NAME_DRIFT" -eq 1 ]; then
        log "WARNING: --allow-name-drift: skipping the name-freeze gate."
        log "WARNING: renamed tools invalidate the Qdrant tool_catalog — plan a re-index (docs/operations/gateway_upgrades.md)."
        return 0
    fi
    log "name-freeze gate: checking tool names in the freshly built gateway image..."
    # The image ships neither pytest nor baseline_tools.txt; feed the baseline
    # via stdin and replicate mcp_gateway/gateway/tests/test_name_freeze.py.
    if ! docker compose run --rm --no-deps -T -e LOG_LEVEL=warning mcp-gateway python -c '
import asyncio, sys
from gateway.app import build_gateway
names = sorted(asyncio.run(build_gateway().get_tools()).keys())
expected = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
missing = sorted(set(expected) - set(names))
added = sorted(set(names) - set(expected))
if names != expected:
    print("NAME-FREEZE VIOLATION: %d missing, %d added" % (len(missing), len(added)))
    print("missing (first 10):", missing[:10])
    print("added (first 10):", added[:10])
    sys.exit(1)
print("name-freeze OK (%d tools)" % len(names))
' < "$REPO_ROOT/mcp_gateway/baseline_tools.txt"; then
        restore_prev_code
        fail "gateway tool names diverged from baseline_tools.txt. Intentional change? Regenerate the baseline and redeploy with --allow-name-drift (docs/operations/gateway_upgrades.md); otherwise fix the gateway before deploying."
    fi
}

confirm() {
    PHASE="confirm"
    log "deploy summary:"
    log "  code:     $PREV_SHA -> ${NEW_SHA:-$PREV_SHA}"
    log "  services: ${SERVICES:-all}"
    log "  backup:   ${BACKUP_DIR:-SKIPPED}"
    if [ "$ASSUME_YES" -ne 1 ]; then
        printf "[redeploy] Press Enter to deploy (Ctrl+C to abort): " >&2
        read -r _
    fi
}

deploy() {
    PHASE="deploy"
    log "deploying (compose recreates only changed containers; postgres/qdrant keep running)..."
    # shellcheck disable=SC2086
    if ! docker compose up -d --wait --wait-timeout 300 $SERVICES; then
        log "deploy failed or containers did not become healthy. Last app logs:"
        docker compose logs --tail=50 app >&2 || true
        fail "deploy failed. Revert code with: bash scripts/deploy/redeploy.sh --rollback${BACKUP_DIR:+ $BACKUP_DIR}"
    fi
}

verify() {
    PHASE="verify"
    local app_port gw_port fe_port code
    app_port="$(getcfg APP_PORT 8000)"
    gw_port="$(getcfg MCP_GATEWAY_PORT 8001)"
    fe_port="$(getcfg FRONTEND_PORT 3001)"

    log "verify: /health ..."
    curl -sf "http://localhost:${app_port}/health" >/dev/null || fail "/health check failed"

    log "verify: polling /ready (tool indexing may take ~30 min after catalog changes)..."
    # READY_TIMEOUT_SECONDS: override the poll ceiling (default 2100 = 35 min)
    local deadline=$(( $(date +%s) + ${READY_TIMEOUT_SECONDS:-2100} )) waited=0 status=""
    while :; do
        status="$(curl -sf "http://localhost:${app_port}/ready" 2>/dev/null \
            | grep -o '"status":"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
        case "$status" in
            ready)
                log "verify: /ready -> ready"; break ;;
            degraded)
                log "WARNING: /ready -> degraded (tool indexing failed)."
                log "WARNING: recoverable without redeploy — see docs/operations/tool_catalog.md."
                break ;;
            *)
                if [ "$(date +%s)" -ge "$deadline" ]; then
                    log "WARNING: /ready still '$status' after ${READY_TIMEOUT_SECONDS:-2100}s; investigate app logs."
                    break
                fi
                if [ "$waited" -eq 60 ]; then
                    log "verify: still initializing — tool indexing in progress; normal after gateway/catalog changes"
                fi
                sleep 10; waited=$((waited + 10)) ;;
        esac
    done

    # SSE endpoint holds the connection open: read the status code with a short timeout
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://localhost:${gw_port}/sse/" || true)"
    [ "$code" = "200" ] && log "verify: gateway /sse/ -> 200" \
        || log "WARNING: gateway /sse/ returned '$code'"

    if docker compose ps --services --status running 2>/dev/null | grep -qx frontend; then
        code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://localhost:${fe_port}/" || true)"
        [ "$code" = "200" ] && log "verify: frontend -> 200" \
            || log "WARNING: frontend returned '$code'"
    fi
}

summary() {
    PHASE="summary"
    log "deploy complete."
    log "  deployed: $(git rev-parse --short HEAD) ($(git log -1 --format=%s))"
    log "  backup:   ${BACKUP_DIR:-SKIPPED}"
    log "  rollback: bash scripts/deploy/redeploy.sh --rollback${BACKUP_DIR:+ $BACKUP_DIR}"
}

do_rollback() {
    PHASE="rollback"
    local dir="$ROLLBACK_DIR" ref
    if [ -z "$dir" ]; then
        dir="$(ls -1d "$REPO_ROOT"/backups/[0-9]*_*/ 2>/dev/null | sort -r | head -n1 || true)"
        [ -n "$dir" ] || fail "no backup directory found under backups/"
        dir="${dir%/}"
    fi
    [ -f "$dir/manifest.txt" ] || fail "no manifest.txt in $dir"
    ref="$(grep '^deploy_prev_ref=' "$dir/manifest.txt" | tail -n1 | cut -d= -f2- || true)"
    [ -n "$ref" ] || ref="$(grep '^git_ref=' "$dir/manifest.txt" | tail -n1 | cut -d= -f2- || true)"
    [ -n "$ref" ] || fail "manifest has no deploy_prev_ref/git_ref to roll back to"

    log "rolling code back to: $ref (from $dir)"
    if [ "$ASSUME_YES" -ne 1 ]; then
        printf "[redeploy] Press Enter to roll back (Ctrl+C to abort): " >&2
        read -r _
    fi
    git checkout "$ref"
    docker compose build
    docker compose up -d --wait --wait-timeout 300
    verify
    log "code rolled back. The database was NOT restored — migrations from the"
    log "failed deploy remain applied (they are additive by policy). If data must"
    log "be restored, follow docs/operations/backup_restore.md using: $dir"
    log "(restoring loses writes made after that dump)."
}

if [ "$ROLLBACK" -eq 1 ]; then
    do_rollback
    exit 0
fi

preflight
do_backup
fetch_code
build_images
name_freeze_gate
confirm
deploy
verify
summary
