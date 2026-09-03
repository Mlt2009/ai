"""Tests for Mehltani's new core: taste memory, the biometric guardian, the
self-evolution pipeline, the subagent factory, and JSON-from-model parsing.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
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
os.environ["RP_ID"] = "localhost"

from server import config, evolution, factory, guardian, jsonish, style_memory  # noqa: E402

config.reload()


def tearDownModule() -> None:
    style_memory.close()
    guardian.close()
    evolution.close()
    _TMP.cleanup()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class StyleVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        conn = style_memory.connect()
        for table in ("verdicts", "traits", "lookbook", "clients", "scouted"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

    def test_yes_no_are_aliased_to_love_pass(self):
        self.assertEqual(style_memory.record_verdict("a coat", "yes")["verdict"], "love")
        self.assertEqual(style_memory.record_verdict("a coat", "no")["verdict"], "pass")

    def test_invalid_verdict_is_rejected(self):
        with self.assertRaises(ValueError):
            style_memory.record_verdict("a coat", "meh")

    def test_attributes_accept_string_or_list(self):
        a = style_memory.record_verdict("dress", "love", attributes="oversized, oxblood")
        b = style_memory.record_verdict("dress", "love", attributes=["Oversized", "Oxblood"])
        self.assertEqual(a["attributes"], ["oversized", "oxblood"])
        self.assertEqual(b["attributes"], ["oversized", "oxblood"])

    def test_love_outweighs_pass_in_scoring(self):
        for _ in range(3):
            style_memory.record_verdict("x", "love", attributes=["oversized"])
        for _ in range(3):
            style_memory.record_verdict("y", "pass", attributes=["cropped"])
        scores = {s["attribute"]: s["score"] for s in style_memory.attribute_scores(min_mentions=1)}
        self.assertGreater(scores["oversized"], 0)
        self.assertLess(scores["cropped"], 0)

    def test_min_mentions_filters_one_off_noise(self):
        style_memory.record_verdict("x", "love", attributes=["rare-tag"])
        scores = style_memory.attribute_scores(min_mentions=2)
        self.assertNotIn("rare-tag", {s["attribute"] for s in scores})

    def test_recency_decays_an_old_verdict_relative_to_a_fresh_one(self):
        from datetime import datetime, timedelta, timezone

        old_time = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
        conn = style_memory.connect()
        conn.execute(
            "INSERT INTO verdicts (created_at, subject, kind, verdict, reason,"
            " attributes, source) VALUES (?,?,?,?,?,?,?)",
            (old_time, "ancient love", "look", "love", "", '["decayed-tag"]', "voice"))
        conn.commit()
        style_memory.record_verdict("fresh love", "love", attributes=["fresh-tag"])
        scores = {s["attribute"]: s["score"] for s in style_memory.attribute_scores(min_mentions=1)}
        # Same weight (single "love" each) but the 400-day-old one is past one
        # half-life (180 days) and should score meaningfully lower.
        self.assertLess(scores["decayed-tag"], scores["fresh-tag"])

    def test_summary_reports_no_data_gracefully(self):
        self.assertIn("no", style_memory.summary().lower())

    def test_summary_surfaces_pinned_rules_and_attributes(self):
        style_memory.set_trait("colour:no-yellow", "never wears yellow")
        # summary() only surfaces attributes attribute_scores() would (at
        # least 2 mentions by default) — a single "oversized" is deliberately
        # treated as an anecdote, not a preference yet.
        style_memory.record_verdict("x", "love", attributes=["oversized"])
        style_memory.record_verdict("y", "love", attributes=["oversized"])
        summary = style_memory.summary()
        self.assertIn("no-yellow", summary)
        self.assertIn("oversized", summary)


class StyleLookbookTests(unittest.TestCase):
    def setUp(self) -> None:
        conn = style_memory.connect()
        for table in ("lookbook", "clients", "scouted"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

    def test_add_and_fetch_look(self):
        look = style_memory.add_look("Editorial 1", pieces="coat, boots", hair="slick bun")
        fetched = style_memory.get_look(look["id"])
        self.assertEqual(fetched["title"], "Editorial 1")
        self.assertEqual(fetched["pieces"], ["coat", "boots"])

    def test_set_look_status(self):
        look = style_memory.add_look("Editorial 2")
        self.assertTrue(style_memory.set_look_status(look["id"], "approved"))
        self.assertEqual(style_memory.get_look(look["id"])["status"], "approved")

    def test_client_upsert_merges_fields(self):
        style_memory.upsert_client("Jordan", colouring="warm, deep")
        style_memory.upsert_client("Jordan", allergies="latex")
        record = style_memory.get_client("Jordan")
        self.assertEqual(record["colouring"], "warm, deep")
        self.assertEqual(record["allergies"], "latex")

    def test_scouted_round_trip(self):
        item = style_memory.add_scouted("Vintage trench", brand="Burberry", price=450,
                                        attributes=["trench", "vintage"])
        self.assertEqual(style_memory.get_scouted(item["id"])["state"], "new")
        style_memory.set_scouted_state(item["id"], "sent")
        self.assertEqual(style_memory.get_scouted(item["id"])["state"], "sent")
        found = style_memory.list_scouted(state="sent")
        self.assertEqual(len(found), 1)


class GuardianGateTests(unittest.TestCase):
    def setUp(self) -> None:
        conn = guardian.connect()
        for table in ("credentials", "audit", "threats"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        guardian._presence.clear()
        guardian._challenges.clear()
        guardian._failures.clear()
        guardian.clear_lockdown()
        os.environ["REQUIRE_BIOMETRIC"] = "true"
        config.reload()

    def tearDown(self) -> None:
        os.environ["REQUIRE_BIOMETRIC"] = "true"
        os.environ.pop("RECOVERY_KEY", None)
        os.environ.pop("AUTO_LOCKDOWN", None)
        config.reload()
        guardian.clear_lockdown()

    def test_unlisted_op_is_never_gated(self):
        guardian.require("not_a_real_op")  # must not raise

    def test_disabled_gate_allows_everything(self):
        os.environ["REQUIRE_BIOMETRIC"] = "false"
        config.reload()
        guardian.require("shutdown")  # must not raise

    def test_gate_denies_without_any_enrolled_device(self):
        with self.assertRaises(guardian.Denied):
            guardian.require("shutdown")

    def test_valid_presence_token_authorises_once_granted(self):
        guardian._presence["tok123"] = {"granted": 0, "expires": 9e18, "credential": "x", "op": ""}
        # A device must still be "enrolled" for require() to reach the presence
        # check rather than short-circuiting on "no fingerprint enrolled".
        conn = guardian.connect()
        conn.execute("INSERT INTO credentials (id, created_at, label, public_key)"
                     " VALUES ('c1','now','dev','a2V5')")
        conn.commit()
        guardian.require("shutdown", presence_token="tok123")  # must not raise

    def test_expired_presence_token_is_rejected(self):
        guardian._presence["expired"] = {"granted": 0, "expires": 1, "credential": "x", "op": ""}
        conn = guardian.connect()
        conn.execute("INSERT INTO credentials (id, created_at, label, public_key)"
                     " VALUES ('c1','now','dev','a2V5')")
        conn.commit()
        with self.assertRaises(guardian.Denied):
            guardian.require("shutdown", presence_token="expired")

    def test_recovery_key_bypasses_even_with_no_device_enrolled(self):
        os.environ["RECOVERY_KEY"] = "correct-horse-battery-staple"
        config.reload()
        guardian.require("shutdown", recovery_key="correct-horse-battery-staple")
        threats = guardian.threat_log()
        self.assertTrue(any(t["kind"] == "recovery_key_used" for t in threats))

    def test_wrong_recovery_key_does_not_bypass(self):
        os.environ["RECOVERY_KEY"] = "correct-horse-battery-staple"
        config.reload()
        with self.assertRaises(guardian.Denied):
            guardian.require("shutdown", recovery_key="wrong-guess")

    def test_lockdown_blocks_protected_ops_even_with_a_valid_token(self):
        guardian._presence["tok"] = {"granted": 0, "expires": 9e18, "credential": "x", "op": ""}
        conn = guardian.connect()
        conn.execute("INSERT INTO credentials (id, created_at, label, public_key)"
                     " VALUES ('c1','now','dev','a2V5')")
        conn.commit()
        guardian.engage_lockdown("test lockdown")
        with self.assertRaises(guardian.Denied):
            guardian.require("shutdown", presence_token="tok")

    def test_audit_log_records_allow_and_deny(self):
        with self.assertRaises(guardian.Denied):
            guardian.require("shutdown")
        denied = guardian.audit_log(only_denied=True)
        self.assertTrue(any(e["op"] == "shutdown" and not e["allowed"] for e in denied))

    def test_brute_force_failures_raise_a_critical_threat(self):
        os.environ["AUTO_LOCKDOWN"] = "false"
        config.reload()
        for _ in range(guardian.MAX_FAILED_BEFORE_ALERT):
            guardian._note_failure("bad assertion")
        threats = guardian.threat_log()
        self.assertTrue(any(t["kind"] == "biometric_bruteforce" and t["severity"] == "critical"
                            for t in threats))

    def test_resolve_threat(self):
        threat = guardian.raise_threat("test", "something looked odd")
        self.assertTrue(guardian.resolve_threat(threat["id"]))
        self.assertEqual(len(guardian.threat_log(unresolved_only=True)), 0)


class GuardianRegistrationGateTests(unittest.TestCase):
    """Adding a second fingerprint must not be possible without confirming an
    existing one — otherwise anyone who reaches the dashboard first could
    plant a permanent backdoor before the real owner enrols."""

    def setUp(self) -> None:
        conn = guardian.connect()
        for table in ("credentials", "audit", "threats"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        guardian._presence.clear()
        guardian._challenges.clear()
        guardian.clear_lockdown()
        os.environ["REQUIRE_BIOMETRIC"] = "true"
        config.reload()

    def tearDown(self) -> None:
        os.environ["REQUIRE_BIOMETRIC"] = "true"
        config.reload()

    def test_finish_registration_requires_presence_when_already_enrolled(self):
        conn = guardian.connect()
        conn.execute("INSERT INTO credentials (id, created_at, label, public_key)"
                     " VALUES ('c1','now','dev','a2V5')")
        conn.commit()
        guardian._challenges["state1"] = {"challenge": b"x", "kind": "register",
                                          "label": "second device",
                                          "expires": __import__("time").time() + 120}
        with self.assertRaises(guardian.Denied):
            guardian.finish_registration("state1", {})


class EvolutionPathSafetyTests(unittest.TestCase):
    def test_refuses_frozen_files(self):
        for frozen in evolution.FROZEN:
            with self.assertRaises(ValueError):
                evolution.check_path(frozen)

    def test_refuses_directory_traversal(self):
        with self.assertRaises(ValueError):
            evolution.check_path("../../etc/passwd")

    def test_refuses_paths_outside_editable_roots(self):
        with self.assertRaises(ValueError):
            evolution.check_path("pyproject.toml")

    def test_refuses_disallowed_extensions(self):
        with self.assertRaises(ValueError):
            evolution.check_path("server/agents/binary.exe")

    def test_allows_a_real_editable_file(self):
        path = evolution.check_path("server/agents/data_agent.py")
        self.assertTrue(path.name.endswith("data_agent.py"))


class EvolutionProposalTests(unittest.TestCase):
    """Note: `verify()` runs THIS test suite in a subprocess sandbox to check a
    proposal (see evolution._run_tests). A test in here that itself calls
    verify() would otherwise trigger that subprocess to run this very suite
    again — including this test — recursing with no base case. evolution.py
    sets MEHLTANI_SANDBOXED_VERIFY=1 on that subprocess precisely so tests can
    detect "I am already running inside someone else's sandbox" and skip."""

    _RECURSION_GUARD = os.environ.get("MEHLTANI_SANDBOXED_VERIFY") == "1"

    def setUp(self) -> None:
        conn = evolution.connect()
        conn.execute("DELETE FROM proposals")
        conn.commit()
        guardian._presence.clear()
        guardian.clear_lockdown()

    def test_propose_with_bad_syntax_is_rejected_before_verify(self):
        proposal = run(evolution.propose(
            "break it", "server/agents/data_agent.py", new_source="def broken(:\n"))
        self.assertEqual(proposal["status"], "rejected")
        self.assertIn("error", proposal)

    @unittest.skipIf(_RECURSION_GUARD, "already inside a sandboxed verify() run")
    def test_propose_and_verify_a_trivial_valid_change(self):
        old = evolution.read_source("server/agents/data_agent.py")
        new = old + "\n# unit test appended comment\n"
        proposal = run(evolution.propose(
            "add a comment", "server/agents/data_agent.py", new_source=new))
        self.assertEqual(proposal["status"], "draft")
        result = run(evolution.verify(proposal["id"]))
        self.assertTrue(result["passed"], result.get("output", "")[-1500:])
        self.assertEqual(evolution.get(proposal["id"])["status"], "verified")
        diff_text = evolution.diff(proposal["id"])
        self.assertIn("unit test appended comment", diff_text)

    @unittest.skipIf(_RECURSION_GUARD, "already inside a sandboxed verify() run")
    def test_apply_is_denied_without_a_fingerprint(self):
        old = evolution.read_source("server/agents/data_agent.py")
        proposal = run(evolution.propose(
            "add a comment", "server/agents/data_agent.py", new_source=old + "\n# x\n"))
        run(evolution.verify(proposal["id"]))
        with self.assertRaises(guardian.Denied):
            evolution.apply(proposal["id"])
        # the live file must be untouched
        self.assertEqual(evolution.read_source("server/agents/data_agent.py"), old)

    def test_apply_refuses_an_unverified_proposal(self):
        old = evolution.read_source("server/agents/data_agent.py")
        proposal = run(evolution.propose(
            "add a comment", "server/agents/data_agent.py", new_source=old + "\n# y\n"))
        result = evolution.apply(proposal["id"])
        self.assertIn("error", result)


class FactoryValidatorTests(unittest.TestCase):
    GOOD = '''\
from __future__ import annotations
from ..base import BaseAgent, tool

class FabricAgent(BaseAgent):
    name = "fabric"
    description = "Knows fabrics."

    @tool("Identify a fabric", subject={"type": "string", "description": "what to check"})
    async def identify(self, subject: str):
        return {"subject": subject, "analysis": "cotton probably"}
'''

    def test_accepts_a_well_formed_agent(self):
        info = factory.validate(self.GOOD)
        self.assertEqual(info["agent_name"], "fabric")
        self.assertEqual(info["tools"], ["identify"])

    def test_rejects_a_banned_import(self):
        bad = self.GOOD.replace("from ..base", "import os\nfrom ..base")
        with self.assertRaises(factory.Rejected):
            factory.validate(bad)

    def test_rejects_eval(self):
        bad = self.GOOD.replace('return {"subject"', 'eval("1"); return {"subject"')
        with self.assertRaises(factory.Rejected):
            factory.validate(bad)

    def test_rejects_dunder_attribute_access(self):
        bad = self.GOOD.replace(
            'return {"subject": subject, "analysis": "cotton probably"}',
            'return {"subject": subject.__class__.__name__}')
        with self.assertRaises(factory.Rejected):
            factory.validate(bad)

    def test_rejects_missing_base_agent_subclass(self):
        bad = "class NotAnAgent:\n    name = 'x'\n"
        with self.assertRaises(factory.Rejected):
            factory.validate(bad)

    def test_rejects_agent_with_no_tools(self):
        bad = '''\
from __future__ import annotations
from ..base import BaseAgent, tool

class FabricAgent(BaseAgent):
    name = "fabric"
    description = "Knows fabrics."

    async def identify(self, subject: str):
        return {"subject": subject, "analysis": "cotton probably"}
'''
        with self.assertRaises(factory.Rejected):
            factory.validate(bad)

    def test_rejects_reserved_name_collision(self):
        bad = self.GOOD.replace('"fabric"', '"guardian"')
        with self.assertRaises(factory.Rejected):
            factory.validate(bad)

    def test_rejects_name_mismatch_with_expectation(self):
        with self.assertRaises(factory.Rejected):
            factory.validate(self.GOOD, expected_name="something_else")

    def test_rejects_malformed_name(self):
        bad = self.GOOD.replace('"fabric"', '"F!"')
        with self.assertRaises(factory.Rejected):
            factory.validate(bad)


class FactoryFilesystemTests(unittest.TestCase):
    """Writes go to a throwaway directory — never the real repo tree."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._original_dir = factory.GENERATED_DIR
        factory.GENERATED_DIR = Path(self._tmp.name) / "generated"
        guardian._presence.clear()

    def tearDown(self) -> None:
        factory.GENERATED_DIR = self._original_dir
        self._tmp.cleanup()

    def test_write_load_and_call_round_trip(self):
        written = factory.write_agent(FactoryValidatorTests.GOOD, "fabric")
        self.assertEqual(written["agent_name"], "fabric")
        agent = factory.load_agent("fabric")
        self.assertEqual(agent.name, "fabric")
        result = run(agent.call("identify", {"subject": "this jacket"}))
        self.assertEqual(result["subject"], "this jacket")

    def test_load_all_includes_generated_agents(self):
        factory.write_agent(FactoryValidatorTests.GOOD, "fabric")
        team = factory.load_all()
        self.assertIn("fabric", team)

    def test_list_generated_reports_metadata(self):
        factory.write_agent(FactoryValidatorTests.GOOD, "fabric")
        listed = factory.list_generated()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], "fabric")

    def test_remove_is_denied_without_a_fingerprint(self):
        factory.write_agent(FactoryValidatorTests.GOOD, "fabric")
        with self.assertRaises(guardian.Denied):
            factory.remove("fabric")
        self.assertIn("fabric", factory.load_all())

    def test_remove_of_unknown_agent_reports_an_error_when_ungated(self):
        os.environ["REQUIRE_BIOMETRIC"] = "false"
        config.reload()
        try:
            result = factory.remove("does-not-exist")
            self.assertIn("error", result)
        finally:
            os.environ["REQUIRE_BIOMETRIC"] = "true"
            config.reload()


class JsonishTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(jsonish.loads('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        self.assertEqual(jsonish.loads('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_wrapped_json(self):
        text = 'Sure, here you go:\n{"a": 1}\nHope that helps!'
        self.assertEqual(jsonish.loads(text), {"a": 1})

    def test_malformed_returns_default(self):
        self.assertEqual(jsonish.loads("not json at all", default={"x": 1}), {"x": 1})

    def test_empty_returns_empty_dict_by_default(self):
        self.assertEqual(jsonish.loads(""), {})


if __name__ == "__main__":
    unittest.main()
