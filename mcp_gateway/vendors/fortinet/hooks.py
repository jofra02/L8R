"""FortiOS-specific spec transforms for the fortinet vendor pack.

Loaded by the gateway via ``vendor_pack.VendorPack._load_hooks``:
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


SPEC_FIXES = [fix_sdwan_monolith]
