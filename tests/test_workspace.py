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

    def test_chatgpt_companion_honours_a_custom_base_url(self):
        """A proxy/Azure key must not be sent to api.openai.com."""
        os.environ["OPENAI_API_KEY"] = "sk-proxy-scoped"
        os.environ["OPENAI_BASE_URL"] = "http://my-proxy.local/v1"
        try:
            config.reload()
            chatgpt = [c for c in council_agent.companions() if c["name"] == "chatgpt"][0]
            self.assertEqual(chatgpt["base_url"], "http://my-proxy.local/v1")
            self.assertEqual(chatgpt["base_url"], config.OPENAI_BASE_URL)
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ.pop("OPENAI_BASE_URL", None)
            config.reload()

    def test_chatgpt_companion_defaults_to_openai(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            config.reload()
            chatgpt = [c for c in council_agent.companions() if c["name"] == "chatgpt"][0]
            self.assertEqual(chatgpt["base_url"], "https://api.openai.com/v1")
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
            config.reload()


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


class InvoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        conn = ledger.connect()
        conn.execute("DELETE FROM invoices")
        conn.commit()

    def test_numbering_is_sequential_within_the_year(self):
        first = ledger.add_invoice("A", items=[{"name": "x", "amount": 10}])
        second = ledger.add_invoice("B", items=[{"name": "y", "amount": 20}])
        year = ledger.date.today().strftime("%Y")
        self.assertEqual(first["number"], f"{year}-0001")
        self.assertEqual(second["number"], f"{year}-0002")

    def test_totals_are_computed_from_line_items(self):
        invoice = ledger.add_invoice(
            "Acme", items=[{"name": "labor", "amount": 120},
                           {"name": "parts", "amount": 40}], tax_rate=8.25)
        self.assertEqual(invoice["subtotal"], 160.0)
        self.assertEqual(invoice["tax"], 13.2)
        self.assertEqual(invoice["total"], 173.2)

    def test_a_percent_and_a_fraction_mean_the_same_rate(self):
        """8.25 and 0.0825 are both natural ways to say the same tax rate."""
        as_percent = ledger.add_invoice("A", items=[{"name": "x", "amount": 100}],
                                        tax_rate=8.25)
        as_fraction = ledger.add_invoice("B", items=[{"name": "x", "amount": 100}],
                                         tax_rate=0.0825)
        self.assertEqual(as_percent["tax"], as_fraction["tax"])

    def test_outstanding_tracks_paid_and_overdue(self):
        ledger.add_invoice("Late", items=[{"name": "x", "amount": 100}],
                           due_on="2020-01-01")
        payable = ledger.add_invoice("Paid", items=[{"name": "x", "amount": 50}])
        before = ledger.outstanding()
        self.assertEqual(before["count"], 2)
        self.assertEqual(before["total"], 150.0)
        self.assertEqual(before["overdue_count"], 1)
        self.assertEqual(before["overdue_total"], 100.0)

        ledger.mark_invoice_paid(payable["id"])
        after = ledger.outstanding()
        self.assertEqual(after["count"], 1)
        self.assertEqual(after["total"], 100.0)

    def test_spoken_line_items_are_parsed(self):
        from server.agents.invoice_agent import _items_from

        items = _items_from("main line snake 120, camera inspection 40.50")
        self.assertEqual([i["name"] for i in items],
                         ["main line snake", "camera inspection"])
        self.assertEqual([i["amount"] for i in items], [120.0, 40.5])

    def test_an_item_with_no_number_still_records_the_label(self):
        from server.agents.invoice_agent import _items_from

        items = _items_from("callout")
        self.assertEqual(items[0]["name"], "callout")
        self.assertEqual(items[0]["amount"], 0.0)


class MileageTests(unittest.TestCase):
    def setUp(self) -> None:
        conn = ledger.connect()
        conn.execute("DELETE FROM trips")
        conn.commit()

    def test_deduction_is_miles_times_rate(self):
        trip = ledger.add_trip(42.5, "service call", rate=0.70)
        self.assertEqual(trip["miles"], 42.5)
        self.assertEqual(trip["deduction"], 29.75)

    def test_totals_sum_over_a_period(self):
        ledger.add_trip(10, rate=0.5, driven_on="2026-03-01")
        ledger.add_trip(20, rate=0.5, driven_on="2026-03-15")
        ledger.add_trip(30, rate=0.5, driven_on="2026-05-01")
        march = ledger.mileage_totals(since="2026-03-01", until="2026-03-31")
        self.assertEqual(march, {"trips": 2, "miles": 30.0, "deduction": 15.0})

    def test_the_rate_is_not_hardcoded_to_a_published_figure(self):
        """A stale IRS rate would put a wrong number on a tax return."""
        self.assertEqual(config.MILEAGE_RATE, 0.0,
                         "MILEAGE_RATE must default to 0 so the agent asks for it")


class JobScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        conn = ledger.connect()
        conn.execute("DELETE FROM jobs")
        conn.commit()

    def test_spoken_times_become_sortable_iso(self):
        from server.agents.jobs_agent import parse_when

        today = ledger.date.today().isoformat()
        self.assertEqual(parse_when("today 2pm"), f"{today}T14:00")
        self.assertEqual(parse_when("today 09:30"), f"{today}T09:30")
        self.assertEqual(parse_when("2026-08-05T14:00"), "2026-08-05T14:00")
        self.assertEqual(parse_when("2026-08-05"), "2026-08-05T08:00")

    def test_tomorrow_advances_a_day(self):
        from datetime import timedelta

        from server.agents.jobs_agent import parse_when

        tomorrow = (ledger.date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(parse_when("tomorrow 8am"), f"{tomorrow}T08:00")

    def test_unreadable_times_raise_rather_than_booking_the_wrong_slot(self):
        from server.agents.jobs_agent import parse_when

        with self.assertRaises(ValueError):
            parse_when("sometime next week maybe")

    def test_jobs_come_back_in_time_order(self):
        ledger.add_job("second", "2026-08-05T14:00")
        ledger.add_job("first", "2026-08-05T09:00")
        self.assertEqual([j["title"] for j in ledger.list_jobs()], ["first", "second"])

    def test_status_changes_stick(self):
        job = ledger.add_job("clear drain", "2026-08-05T09:00")
        ledger.update_job(job["id"], status="done")
        self.assertEqual(ledger.get_job(job["id"])["status"], "done")
        self.assertEqual(ledger.list_jobs(status="scheduled"), [])


class PdfTests(unittest.TestCase):
    def test_output_is_a_well_formed_pdf(self):
        from server import pdf

        blob = pdf.build("INVOICE 2026-0001\nTOTAL DUE  $173.20")
        self.assertTrue(blob.startswith(b"%PDF-1.4"))
        self.assertTrue(blob.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/BaseFont /Courier", blob)
        self.assertIn(b"(INVOICE 2026-0001) Tj", blob)

    def test_the_xref_offsets_actually_point_at_their_objects(self):
        from server import pdf

        blob = pdf.build("hello")
        tail = blob[blob.rindex(b"startxref"):]
        xref_at = int(tail.split(b"\n")[1])
        self.assertEqual(blob[xref_at:xref_at + 4], b"xref")
        rows = blob[xref_at:].split(b"\n")[2:]
        for number, row in enumerate(rows[1:], start=1):   # skip the free entry
            if not row.strip() or row.startswith(b"trailer"):
                break
            offset = int(row.split()[0])
            self.assertEqual(blob[offset:offset + len(f"{number} 0 obj")],
                             f"{number} 0 obj".encode())

    def test_long_documents_paginate(self):
        from server import pdf

        blob = pdf.build("\n".join(f"line {i}" for i in range(200)))
        self.assertGreater(blob.count(b"/Type /Page /Parent"), 1)

    def test_parentheses_and_backslashes_do_not_corrupt_the_stream(self):
        from server import pdf

        blob = pdf.build(r"Tax (8.25%) \ path")
        self.assertIn(rb"(Tax \(8.25%\) \\ path) Tj", blob)


class MailTests(unittest.TestCase):
    """No network: only the message the agent would hand to SMTP."""

    def test_a_message_with_an_attachment_is_assembled(self):
        import tempfile as tf

        from server.agents.mail_agent import _build

        with tf.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as handle:
            handle.write(b"%PDF-1.4 fake")
            path = handle.name
        message = _build("customer@example.com", "Invoice 2026-0001", "Attached.", path)
        self.assertEqual(message["To"], "customer@example.com")
        self.assertEqual(message["Subject"], "Invoice 2026-0001")
        names = [part.get_filename() for part in message.iter_attachments()]
        self.assertIn(Path(path).name, names)

    def test_a_missing_attachment_is_reported_not_silently_dropped(self):
        from server.agents.mail_agent import _build

        with self.assertRaises(FileNotFoundError):
            _build("a@b.com", "s", "b", "/no/such/file.pdf")

    def test_sending_without_credentials_explains_what_is_missing(self):
        from server.agents.mail_agent import _require_smtp

        with self.assertRaises(RuntimeError) as caught:
            _require_smtp()
        self.assertIn("SMTP_HOST", str(caught.exception))
