import unittest
from datetime import datetime, timedelta, timezone

from hybrid_ai import contracts as c

NOW = datetime(2026, 11, 8, 14, 0, tzinfo=timezone.utc)
EXPECTED_TOOLS = {
    "diagnose_issue", "find_technicians", "recommend_repair_location", "check_parts",
    "reserve_parts", "search_knowledge", "get_live_telemetry", "update_work_order",
}


class ContractLoading(unittest.TestCase):
    def test_all_design_tools_present(self):
        self.assertEqual(set(c.list_tools()), EXPECTED_TOOLS)

    def test_schemas_are_valid_json_schema(self):
        from jsonschema import Draft202012Validator
        for name in c.list_tools():
            t = c.get_tool(name)
            for schema in (t.input_schema, t.output_schema, t.response_schema):
                Draft202012Validator.check_schema(schema)

    def test_unknown_tool(self):
        with self.assertRaises(KeyError):
            c.get_tool("launch_rocket")


class InputValidation(unittest.TestCase):
    def test_valid_diagnose(self):
        c.validate_input("diagnose_issue", {"asset_id": "AST-00004", "symptoms": ["arc marks"]})

    def test_bad_asset_id(self):
        with self.assertRaises(c.ContractError) as cm:
            c.validate_input("diagnose_issue", {"asset_id": "pump-7"})
        self.assertIn("asset_id", str(cm.exception))

    def test_extra_fields_rejected(self):
        with self.assertRaises(c.ContractError):
            c.validate_input("diagnose_issue", {"asset_id": "AST-00004", "shutdown": True})

    def test_check_parts_needs_parts_or_cause(self):
        with self.assertRaises(c.ContractError):
            c.validate_input("check_parts", {"technician_id": "TEC-0001"})
        c.validate_input("check_parts", {"cause_code": "PMP-BRG-WEAR"})
        c.validate_input("check_parts", {"part_numbers": ["P-PMP-0101"], "near": {"lat": 36.7, "lon": -119.8}})

    def test_writes_require_idempotency_key(self):
        with self.assertRaises(c.ContractError):
            c.validate_input("update_work_order", {"work_order_id": "WO-2026-0001", "patch": {"status": "assigned"}})
        c.validate_input("update_work_order", {
            "work_order_id": "WO-2026-0001", "patch": {"status": "assigned"}, "idempotency_key": "dev1-000042",
        })

    def test_empty_patch_rejected(self):
        with self.assertRaises(c.ContractError):
            c.validate_input("update_work_order", {
                "work_order_id": "WO-2026-0001", "patch": {}, "idempotency_key": "dev1-000042"})


class Envelope(unittest.TestCase):
    DIAG = {
        "asset_id": "AST-00004",
        "causes": [{"cause_code": "XFM-BUSH-CRACK", "description": "Cracked HV bushing", "probability": 0.8}],
        "severity": "critical",
        "safe_to_run": False,
        "safety_override": True,
    }

    def test_cloud_is_authoritative_by_default(self):
        env = c.envelope(self.DIAG, source_tier="cloud", as_of=NOW, now=NOW)
        self.assertTrue(env["authoritative"])
        self.assertEqual(env["confidence"], "confirmed")
        c.validate_response("diagnose_issue", env)

    def test_field_answer_is_provisional_and_stale(self):
        env = c.envelope(self.DIAG, source_tier="field", as_of=NOW - timedelta(hours=5), now=NOW)
        self.assertFalse(env["authoritative"])
        self.assertEqual(env["confidence"], "provisional")
        self.assertEqual(env["staleness_s"], 5 * 3600)
        self.assertTrue(env["as_of"].endswith("Z"))
        c.validate_response("diagnose_issue", env)

    def test_response_without_provenance_rejected(self):
        with self.assertRaises(c.ContractError):
            c.validate_response("diagnose_issue", {"result": self.DIAG})

    def test_bad_result_rejected(self):
        bad = dict(self.DIAG, severity="apocalyptic")
        with self.assertRaises(c.ContractError):
            c.validate_response("diagnose_issue", c.envelope(bad, source_tier="cloud", as_of=NOW, now=NOW))

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            c.envelope(self.DIAG, source_tier="cloud", as_of=datetime(2026, 11, 8), now=NOW)

    def test_unknown_tier_rejected(self):
        with self.assertRaises(ValueError):
            c.envelope(self.DIAG, source_tier="moon", as_of=NOW, now=NOW)


if __name__ == "__main__":
    unittest.main()
