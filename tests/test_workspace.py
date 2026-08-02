"""Tests for the shopping/finance workspace: ledger, slip layout, path safety.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _TMP.name
os.environ["FILE_ROOTS"] = _TMP.name
os.environ["ALLOW_FILE_WRITE"] = "false"

from server import brain, config, ledger, receipt_layout  # noqa: E402
from server.agents import council_agent, files_agent, scan_agent  # noqa: E402

config.reload()


def tearDownModule() -> None:
    ledger.close()
    _TMP.cleanup()


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        conn = ledger.connect()
        for table in ("receipts", "shopping_items", "budgets"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

    def test_total_is_derived_when_only_parts_are_legible(self):
        """A receipt photo often yields subtotal + tax but no total line."""
        receipt = ledger.add_receipt(merchant="Ace Hardware", subtotal=100, tax=8.25)
        self.assertEqual(receipt["total"], 108.25)

    def test_total_is_derived_from_line_items(self):
        receipt = ledger.add_receipt(
            merchant="Depot",
            items=[{"name": "pipe", "amount": 12.5}, {"name": "flux", "amount": 4.25}])
        self.assertEqual(receipt["total"], 16.75)

    def test_currency_strings_are_parsed_not_dropped(self):
        receipt = ledger.add_receipt(merchant="Shell", total="$1,234.56")
        self.assertEqual(receipt["total"], 1234.56)

    def test_unreadable_amount_becomes_zero_rather_than_crashing(self):
        receipt = ledger.add_receipt(merchant="Smudged", total="~~illegible~~")
        self.assertEqual(receipt["total"], 0.0)

    def test_filters_and_grouping(self):
        ledger.add_receipt(merchant="Kroger", total=40, category="groceries",
                           purchased_on="2026-03-02")
        ledger.add_receipt(merchant="Kroger", total=60, category="groceries",
                           purchased_on="2026-03-09")
        ledger.add_receipt(merchant="Shell", total=55, category="fuel",
                           purchased_on="2026-04-01")

        march = ledger.list_receipts(since="2026-03-01", until="2026-03-31")
        self.assertEqual(len(march), 2)
        self.assertEqual([r["merchant"] for r in march], ["Kroger", "Kroger"])

        by_category = {g["group_key"]: g["total"] for g in ledger.totals("category")}
        self.assertEqual(by_category, {"groceries": 100.0, "fuel": 55.0})

        by_month = {g["group_key"]: g["total"] for g in ledger.totals("month")}
        self.assertEqual(by_month["2026-03"], 100.0)

    def test_budget_status_flags_overspend(self):
        month = ledger.date.today().strftime("%Y-%m")
        ledger.set_budget("groceries", 50)
        ledger.add_receipt(merchant="Kroger", total=75, category="groceries",
                           purchased_on=f"{month}-05")
        status = {row["category"]: row for row in ledger.budget_status()}
        self.assertTrue(status["groceries"]["over_budget"])
        self.assertEqual(status["groceries"]["remaining"], -25.0)

    def test_shopping_list_round_trip(self):
        ledger.add_item("milk", qty="2", store="Kroger")
        ledger.add_item("copper pipe", store="Home Depot")
        self.assertEqual(len(ledger.list_items()), 2)

        self.assertEqual(ledger.check_off("MILK"), 1)  # case-insensitive
        self.assertEqual(len(ledger.list_items()), 1)
        self.assertEqual(len(ledger.list_items(include_done=True)), 2)

        self.assertEqual(ledger.clear_items(done_only=True), 1)
        self.assertEqual(len(ledger.list_items(include_done=True)), 1)


class SlipLayoutTests(unittest.TestCase):
    """The layout replaces the shortcut's fixed 'lines 15 to 28' slicing."""

    receipt = {
        "id": 42,
        "merchant": "Redman's Drain Cleaning",
        "purchased_on": "2026-04-18",
        "subtotal": 160.0,
        "tax": 13.20,
        "total": 173.20,
        "currency": "USD",
        "category": "services",
        "payment_method": "VISA ****4242",
        "note": "Invoice 10032",
        "items": [{"name": "Main line snake, 75 ft", "qty": "1", "amount": 120.0},
                  {"name": "Camera inspection", "qty": "1", "amount": 40.0}],
    }

    def test_every_line_fits_the_paper(self):
        for width in (24, 32, 40, 64):
            slip = receipt_layout.render(self.receipt, width=width)
            for line in slip.splitlines():
                self.assertLessEqual(len(line), width,
                                     f"line overflows {width}-char paper: {line!r}")

    def test_key_fields_survive_the_render(self):
        slip = receipt_layout.render(self.receipt, width=40)
        self.assertIn("REDMAN'S DRAIN CLEANING", slip)
        self.assertIn("2026-04-18", slip)
        self.assertIn("$173.20", slip)
        self.assertIn("Camera inspection", slip)
        self.assertIn("#0042", slip)

    def test_long_item_names_wrap_instead_of_truncating(self):
        receipt = dict(self.receipt, items=[
            {"name": "Emergency after-hours sewer line hydro jetting service call",
             "qty": "1", "amount": 450.0}])
        slip = receipt_layout.render(receipt, width=32)
        self.assertIn("hydro", slip)
        self.assertIn("$450.00", slip)

    def test_a_nearly_empty_receipt_still_renders(self):
        slip = receipt_layout.render({"total": 0})
        self.assertIn("TOTAL", slip)


class PathSafetyTests(unittest.TestCase):
    def test_scan_rejects_directory_traversal(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            scan_agent.resolve_image("../../etc/passwd")

    def test_scan_finds_a_real_upload(self):
        shot = scan_agent.uploads_dir() / "unit-test.jpg"
        shot.write_bytes(b"not really a jpeg")
        try:
            self.assertEqual(scan_agent.resolve_image("unit-test.jpg"), shot.resolve())
        finally:
            shot.unlink()

    def test_files_agent_refuses_paths_outside_its_roots(self):
        with self.assertRaises(PermissionError):
            files_agent.resolve("/etc/shadow")

    def test_files_agent_allows_paths_inside_its_roots(self):
        inside = Path(config.FILE_ROOTS) / "notes.txt"
        self.assertEqual(files_agent.resolve(str(inside)), inside.resolve())

    def test_writes_are_refused_until_explicitly_enabled(self):
        with self.assertRaises(PermissionError):
            files_agent.require_write()
        os.environ["ALLOW_FILE_WRITE"] = "true"
        config.reload()
        try:
            files_agent.require_write()  # must not raise
        finally:
            os.environ["ALLOW_FILE_WRITE"] = "false"
            config.reload()


class CompanionRegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("COMPANION_ENDPOINTS", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        config.reload()

    def test_custom_endpoints_are_parsed(self):
        os.environ["COMPANION_ENDPOINTS"] = (
            "ollama|http://localhost:11434/v1|llama3|,"
            "router|https://router.local/v1|auto|secret")
        config.reload()
        found = {c["name"]: c for c in council_agent.companions()}
        self.assertEqual(found["ollama"]["base_url"], "http://localhost:11434/v1")
        self.assertEqual(found["ollama"]["key"], "")
        self.assertEqual(found["router"]["model"], "auto")
        self.assertEqual(found["router"]["key"], "secret")

    def test_malformed_endpoint_entries_are_skipped(self):
        os.environ["COMPANION_ENDPOINTS"] = "broken,also|broken"
        config.reload()
        self.assertEqual(council_agent._custom_companions(), [])

    def test_a_configured_key_registers_a_companion(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        config.reload()
        claude = [c for c in council_agent.companions() if c["name"] == "claude"]
        self.assertEqual(len(claude), 1)
        self.assertEqual(claude[0]["kind"], "anthropic")


class BrainSelectionTests(unittest.TestCase):
    """One key — either key — has to be enough to run the whole workspace."""

    def tearDown(self) -> None:
        for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "BRAIN_PROVIDER"):
            os.environ.pop(key, None)
        config.reload()

    def _set(self, **env):
        for key, value in env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reload()

    def test_no_keys_means_no_brain(self):
        self._set()
        self.assertEqual(brain.provider(), "")
        with self.assertRaises(brain.NoBrain):
            brain.require()

    def test_openai_key_alone_is_enough(self):
        self._set(OPENAI_API_KEY="sk-test")
        self.assertEqual(brain.provider(), "openai")
        self.assertEqual(brain.model_name(), config.OPENAI_MODEL)

    def test_gemini_key_alone_is_enough(self):
        self._set(GEMINI_API_KEY="g-test")
        self.assertEqual(brain.provider(), "gemini")

    def test_gemini_wins_by_default_when_both_are_set(self):
        self._set(GEMINI_API_KEY="g-test", OPENAI_API_KEY="sk-test")
        self.assertEqual(brain.provider(), "gemini")

    def test_provider_can_be_pinned(self):
        self._set(GEMINI_API_KEY="g-test", OPENAI_API_KEY="sk-test",
                  BRAIN_PROVIDER="openai")
        self.assertEqual(brain.provider(), "openai")

    def test_pinning_a_provider_without_its_key_reports_no_brain(self):
        self._set(OPENAI_API_KEY="sk-test", BRAIN_PROVIDER="gemini")
        self.assertEqual(brain.provider(), "")


class ToolSchemaTests(unittest.TestCase):
    """A tool is declared once and both brains have to be able to call it."""

    def setUp(self) -> None:
        from server.agents import ShoppingAgent

        self.agent = ShoppingAgent()

    def _find(self, decls, name, unwrap=False):
        for decl in decls:
            body = decl["function"] if unwrap else decl
            if body["name"] == name:
                return body
        self.fail(f"{name} missing from declarations")

    def test_openai_declarations_are_wrapped_functions(self):
        decl = self._find(self.agent.openai_declarations(), "shopping__add_to_list",
                          unwrap=True)
        self.assertEqual(self.agent.openai_declarations()[0]["type"], "function")
        self.assertEqual(decl["parameters"]["type"], "object")
        self.assertEqual(decl["parameters"]["properties"]["item"]["type"], "string")
        self.assertEqual(decl["parameters"]["required"], ["item"])

    def test_gemini_declarations_use_upper_case_types(self):
        decl = self._find(self.agent.gemini_declarations(), "shopping__add_to_list")
        self.assertEqual(decl["parameters"]["type"], "OBJECT")
        self.assertEqual(decl["parameters"]["properties"]["item"]["type"], "STRING")

    def test_both_brains_see_the_same_tools(self):
        neutral = {d["name"] for d in self.agent.tool_declarations()}
        gemini = {d["name"] for d in self.agent.gemini_declarations()}
        openai = {d["function"]["name"] for d in self.agent.openai_declarations()}
        self.assertEqual(neutral, gemini)
        self.assertEqual(neutral, openai)


class ToolCallParsingTests(unittest.TestCase):
    def test_arguments_are_decoded(self):
        message = {"tool_calls": [{"id": "call_1", "type": "function", "function": {
            "name": "shopping__add_to_list", "arguments": '{"item": "milk", "qty": "2"}'}}]}
        self.assertEqual(brain.parse_tool_calls(message),
                         [{"id": "call_1", "name": "shopping__add_to_list",
                           "args": {"item": "milk", "qty": "2"}}])

    def test_malformed_arguments_degrade_to_empty_rather_than_crashing(self):
        message = {"tool_calls": [{"id": "c", "type": "function", "function": {
            "name": "x", "arguments": "{not json"}}]}
        self.assertEqual(brain.parse_tool_calls(message)[0]["args"], {})

    def test_a_plain_answer_has_no_tool_calls(self):
        self.assertEqual(brain.parse_tool_calls({"content": "hello"}), [])


class ResponsesParsingTests(unittest.TestCase):
    def test_convenience_field_is_preferred(self):
        self.assertEqual(brain._responses_text({"output_text": " $12.99 at Ace "}),
                         "$12.99 at Ace")

    def test_falls_back_to_walking_the_output_array(self):
        body = {"output": [{"content": [{"type": "output_text", "text": "line one"},
                                        {"type": "output_text", "text": "line two"}]}]}
        self.assertEqual(brain._responses_text(body), "line one\nline two")

    def test_an_unrecognised_shape_yields_empty_not_an_exception(self):
        self.assertEqual(brain._responses_text({"weird": True}), "")


if __name__ == "__main__":
    unittest.main()
