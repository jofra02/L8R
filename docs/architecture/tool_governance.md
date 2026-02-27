# Tool Governance

The system enforces a **two-layer safety model** before any tool execution. Both layers must pass for a tool call to proceed.

```
Tool Request → Layer 1: Keyword Blocklist → Layer 2: Tenant Allowlist → Execute
                    ↓ BLOCK                      ↓ BLOCK
                  (skip tool)                  (skip tool)
```

---

## Layer 1: Keyword Blocklist (`is_safe_tool`)

**Where:** `src/core/safety.py` · synchronous  
**Scope:** Global — applies to all tenants equally  
**Fail mode:** Fail-closed (block)

Blocks tool execution if the tool name or any argument value contains a dangerous keyword. Designed to prevent write/destructive operations that the agent should never perform autonomously.

### Blocked Keywords

Configured in `src/config.py` → `SAFETY_BLOCKED_KEYWORDS`:

```python
SAFETY_BLOCKED_KEYWORDS = [
    "debug flow", "sniffer", "packet capture", "pcap", "tcpdump", "wireshark",
    "execute", "configure", "set ", "edit ", "delete", "rm ", "shutdown", "reboot"
]
```

### What Gets Checked

| Check | Example |
|:---|:---|
| Tool name | Tool `configure_interface` → blocked by `"configure"` |
| Argument values | `{"command": "set system dns"}` → blocked by `"set "` |

### Customization

Override via `.env` or `config.py`. The list uses **substring matching** (case-insensitive):

```ini
# .env (JSON-encoded list)
SAFETY_BLOCKED_KEYWORDS=["delete","shutdown","reboot","execute"]
```

---

## Layer 2: Tenant Allowlist (`is_tool_allowed_for_tenant`)

**Where:** `src/core/safety.py` · async  
**Scope:** Per-tenant — each tenant has its own tool allowlist  
**Fail mode:** Fail-open (allow)

Queries the `capability_scopes` PostgreSQL table to determine if a specific tool is allowed for a given tenant.

### ORM Model

```python
# src/core/orm.py
class CapabilityScope(Base):
    __tablename__ = "capability_scopes"

    id: int                  # Auto-increment PK
    customer_id: str         # FK → platform_tenants.customer_id
    scope_name: str          # Human label, e.g. "network_read"
    allowed_tools: List[str] # JSON array of glob patterns
    rate_limit: int | None   # Future: max calls/hour (not enforced yet)
    created_at: datetime     # Auto-set
```

### Pattern Matching

`allowed_tools` supports **glob patterns** via Python's `fnmatch`:

| Pattern | Matches |
|:---|:---|
| `"ping"` | Exact match: only `ping` |
| `"fortios_*"` | All FortiOS tools |
| `"*_status"` | Any tool ending in `_status` |
| `"*"` | Everything (open access) |

### Configuration Examples

**Restrict a tenant to read-only network tools:**

```sql
INSERT INTO capability_scopes (customer_id, scope_name, allowed_tools)
VALUES ('acme_corp', 'network_read', '["ping", "traceroute", "fortios_get_*", "dns_lookup"]');
```

**Grant full access to a premium tenant:**

```sql
INSERT INTO capability_scopes (customer_id, scope_name, allowed_tools)
VALUES ('premium_client', 'full_access', '["*"]');
```

**Multiple scopes per tenant (union of all):**

```sql
-- Network tools
INSERT INTO capability_scopes (customer_id, scope_name, allowed_tools)
VALUES ('acme_corp', 'network', '["ping", "traceroute", "fortios_get_*"]');

-- Monitoring tools
INSERT INTO capability_scopes (customer_id, scope_name, allowed_tools)
VALUES ('acme_corp', 'monitoring', '["zabbix_*", "grafana_query"]');
```

All scopes for a tenant are evaluated as a **union**: if any scope allows the tool, it passes.

### Behavior When No Scopes Defined

If a tenant has **zero rows** in `capability_scopes`, all tools are allowed. This ensures backward compatibility for tenants that haven't been configured yet.

---

## Enforcement Points

Both checks run in two agents before any tool is executed:

| Agent | File | Line |
|:---|:---|:---|
| Evidence Collector | `src/agents/evidence_collector.py` | After tool selection loop |
| Investigator | `src/agents/investigator.py` | Before `AdaptiveExecutor.execute()` |

Additionally, `CapabilityRegistry` (tool discovery) filters tools at **registration time** using the keyword blocklist, so blocked tools never appear in the available tool list.

---

## Observability

Both layers log warnings on blocks:

```
# Layer 1
WARNING - Safety Block: Tool 'configure_vdom' blocked by keyword 'configure'

# Layer 2
WARNING - Governance Block: Tool 'fortios_delete_policy' not allowed for tenant 'acme_corp'
```

If the database is unavailable, Layer 2 logs a warning and **allows** the tool (fail-open):

```
WARNING - Governance check failed (allowing): Connection refused
```
