"""FortiOS-specific spec transforms for the fortinet/fortigate appliance pack.

Loaded by the gateway via ``vendor_pack.AppliancePack._load_hooks``:
- ``SPEC_FIXES`` runs after the generic schema fixes, per spec file.
- ``PARAMETER_DOC_APPENDS`` extends parameter descriptions in every operation.
"""

import copy
import logging

logger = logging.getLogger("vendors.fortinet")

# FortiOS filter query syntax — appended to every 'filter' parameter so the
# LLM builds valid expressions. NAME-FREEZE note: text is byte-identical to
# the original suite (it is part of the indexed tool descriptions).
FILTER_SYNTAX_HELP = (
    "\n\n**Syntax Helper**:\n"
    "Format: `key operator value`\n"
    "Operators:\n"
    "  `==` (Equal), `!=` (Not Equal)\n"
    "  `=@` (Contains), `!@` (Not Contains)\n"
    "  `<=` (Less/Eq), `<` (Less), `>=` (Greater/Eq), `>` (Greater)\n"
    "Examples: `srcip==10.1.1.1`, `dstport>80`, `action!=deny`"
)

PARAMETER_DOC_APPENDS = {"filter": FILTER_SYNTAX_HELP}


def fix_sdwan_monolith(spec: dict) -> dict:
    """Split the monolithic /system/sdwan endpoint into granular sub-endpoints
    for service (rules), members and zones.
    """
    paths = spec.get("paths", {})

    # Find the monolithic endpoint (the path may be prefixed)
    monolith_path = None
    monolith_val = None

    for p, val in paths.items():
        if p.endswith("/system/sdwan"):
            monolith_path = p
            monolith_val = val
            break

    if not monolith_path:
        return spec

    logger.info(f"Detected monolithic SD-WAN endpoint at {monolith_path}. Applying split...")

    # Extract the schema from the GET response
    try:
        get_op = monolith_val.get("get")
        if not get_op:
            return spec

        schema = get_op.get("responses", {}).get("200", {}).get("schema", {})
        properties = schema.get("properties", {})

        # Sub-tables to extract
        sub_tables = ["service", "members", "zone"]

        for sub in sub_tables:
            if sub in properties:
                new_path = f"{monolith_path}/{sub}"

                # Copy the original GET op to preserve tags, security, etc.
                new_op = copy.deepcopy(get_op)

                # e.g. get_system_sdwan -> get_system_sdwan_service
                original_op_id = new_op.get("operationId", "get_system_sdwan")
                new_op["operationId"] = f"{original_op_id}_{sub}"

                new_op["summary"] = f"Retrieve SD-WAN {sub} configuration (Sub-table)"

                # Generic dictionary response to avoid Pydantic generation errors
                new_op["responses"]["200"]["schema"] = {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                    "description": f"List of {sub} items (Schema simplified for compatibility)"
                }

                if "tags" in new_op:
                    new_op["tags"].append("sdwan-subtable")

                spec["paths"][new_path] = {
                    "get": new_op
                }

                logger.info(f"  - Generated split endpoint: {new_path}")

    except Exception as e:
        logger.error(f"Failed to split SD-WAN monolith: {e}")

    return spec


# Vocabulary bridge for the license/entitlement snapshot: the stock summary
# ("Get current license & registration status") says nothing about signature
# versions or update timestamps, so semantic tool search never surfaces it for
# queries like "IPS definitions version". Appending response vocabulary fixes
# discoverability. Name-freeze safe: descriptions change, operationIds do not.
LICENSE_STATUS_DOC_APPEND = (
    "\nResponse includes, per security service (IPS engine and definitions, "
    "antivirus/AV definitions, application control, web filtering, anti-spam, "
    "industrial DB, internet service DB, mobile/AI malware, security rating, "
    "outbreak prevention) and for FortiCare registration, support contract and "
    "VM license: entitlement status (licensed, expired, pending), expiration "
    "date, installed signature database version, engine version, last update "
    "time, last update attempt and result. Primary tool to verify installed "
    "definition/signature versions and when they were last updated."
)


def enrich_license_status(spec: dict) -> dict:
    """Append response vocabulary to /license/status so tool search can find it."""
    for path, ops in spec.get("paths", {}).items():
        if path.endswith("/license/status") and isinstance(ops.get("get"), dict):
            op = ops["get"]
            if op.get("summary"):
                op["summary"] = op["summary"] + LICENSE_STATUS_DOC_APPEND
                logger.info(f"Enriched {path} GET summary for tool-search discoverability.")
    return spec


# Vocabulary bridge for historical log retrieval: the stock summaries ("Log
# data for the given log type...") say nothing about web browsing, visited
# URLs, or where the logs are stored, so semantic tool search never surfaces
# the retrieval tools — whose names for local disk lack the word "log"
# entirely (fgt_cmdb_disk_get_*). All four backend families (disk, memory,
# FortiAnalyzer, FortiCloud) get the same append so no backend is demoted.
# Name-freeze safe: descriptions change, operationIds do not.

_LOG_BACKEND_LABELS = {
    "/disk/": "stored locally on the device's disk",
    "/memory/": "stored locally in device memory (volatile, recent window)",
    "/fortianalyzer/": "stored on the connected FortiAnalyzer",
    "/forticloud/": "stored in FortiCloud",
}

LOG_RETRIEVAL_DOC_APPEND = (
    "\nRetrieves historical log entries {backend}. Log categories (type): "
    "traffic, event, webfilter (web browsing history, visited websites/URLs, "
    "web navigation per host), virus, ips, dns, app-ctrl, anomaly, ssl. "
    "Filter entries with expressions like srcip==<ip> to get the activity of "
    "a specific host. Use for questions like: what websites did a host "
    "visit, historical traffic/security/web logs, past events."
)

DEVICE_STATE_DOC_APPEND = (
    "\nReports which log storage backends are enabled and available on this "
    "device: local disk, local memory, FortiAnalyzer, FortiCloud. Call this "
    "FIRST when retrieving historical logs (traffic, web browsing, events) "
    "to pick a backend that actually holds data."
)


def enrich_log_retrieval(spec: dict) -> dict:
    """Append storage/vocabulary context to log retrieval + device-state ops."""
    base = spec.get("basePath", "")
    for path, ops in spec.get("paths", {}).items():
        op = ops.get("get")
        if not isinstance(op, dict) or not op.get("summary"):
            continue
        if base == "/api/v2/log":
            for prefix, label in _LOG_BACKEND_LABELS.items():
                if path.startswith(prefix):
                    op["summary"] = op["summary"] + LOG_RETRIEVAL_DOC_APPEND.format(backend=label)
                    logger.info(f"Enriched {path} GET summary for log-retrieval discoverability.")
                    break
        elif path.endswith("/log/device/state"):
            op["summary"] = op["summary"] + DEVICE_STATE_DOC_APPEND
            logger.info(f"Enriched {path} GET summary for log-retrieval discoverability.")
    return spec


SPEC_FIXES = [fix_sdwan_monolith, enrich_license_status, enrich_log_retrieval]
