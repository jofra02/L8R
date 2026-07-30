"""Ticket normalization: internal PK uniqueness vs source-system identity.

Regression for the duplicate-key crash on resubmission: the normalizer used
md5(payload) (or the payload's own id/ticket_id) as the ticket PK, so the same
text submitted twice — or the same ITSM id from two tenants — collided on the
global tickets_pkey. Internal ids are now always unique; source identity lives
in external_id.

Run: uv run pytest src/testing/test_ingestion_normalizer.py
"""

from src.ingestion.normalizers.generic import GenericNormalizer


def _normalize(payload):
    return GenericNormalizer().normalize(payload, source_id="webhook:api")


def test_identical_payloads_get_distinct_ids():
    payload = {"text": "VPN entre sitios caida", "severity": "medium", "mode": "incident"}
    t1 = _normalize(dict(payload))
    t2 = _normalize(dict(payload))
    assert t1.id != t2.id


def test_payload_id_is_not_used_as_pk():
    t1 = _normalize({"id": "INC0010001", "text": "issue"})
    t2 = _normalize({"id": "INC0010001", "text": "issue"})
    assert t1.id != "INC0010001"
    assert t1.id != t2.id
    # Source identity is preserved for correlation/dedup
    assert t1.external_id == "INC0010001"


def test_external_id_precedence():
    t = _normalize({"external_id": "EXT-1", "id": "INC-2", "ticket_id": "TK-3", "text": "x"})
    assert t.external_id == "EXT-1"


def test_ticket_id_fallback_to_external_id():
    t = _normalize({"ticket_id": "TK-3", "text": "x"})
    assert t.external_id == "TK-3"


def test_no_source_identity_leaves_external_id_none():
    t = _normalize({"text": "x", "external_id": None})
    assert t.external_id is None
    assert len(t.id) == 32
