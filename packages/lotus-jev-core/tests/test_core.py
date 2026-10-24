"""Host injection and recovery behavior, without browsers or inference."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_ultrafast import agent, browser, model


class CoreTests(unittest.TestCase):
    def test_snapshot_script_is_packaged_beside_browser_module(self):
        self.assertIn("__jevFast", browser.READ_STATE)

    def test_snapshot_retains_disabled_values_and_absolute_links_without_sensitive_fields(self):
        subprocess.run(
            ["node", str(Path(__file__).with_name("snapshot-fixture.mjs")), str(Path(browser.__file__).with_name("snapshot.js"))],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_action_space_retains_observed_link_destination(self):
        action = {
            "id": "link-1",
            "kind": "click",
            "node": 1,
            "label": "View listing",
            "role": "link",
            "href": "https://listings.example/cars/42?currency=USD",
        }
        elements, targets, _ = model.action_space([action])
        self.assertEqual(elements[0]["href"], action["href"])
        self.assertEqual(targets["CLICK"]["1"]["href"], action["href"])

    def test_document_reader_captures_offscreen_rendered_evidence_with_explicit_limits(self):
        supplied = browser.Browser.__new__(browser.Browser)
        supplied.evaluate = Mock(return_value={"text": "observed"})
        self.assertEqual(supplied.read_document(), {"text": "observed"})
        subprocess.run(
            ["node", str(Path(__file__).with_name("document-fixture.mjs"))],
            input=supplied.evaluate.call_args.args[0],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_provider_io_requires_a_host_relay(self):
        with patch.object(model, "RELAY", None), self.assertRaisesRegex(RuntimeError, "relay is not configured"):
            model.post_json("jev", {"goal": "test"})
        relay = Mock(return_value={"answer": "observed"})
        with patch.object(model, "RELAY", relay):
            self.assertEqual(model.post_json("jev", {"goal": "test"}), {"answer": "observed"})
        relay.assert_called_once_with("jev", {"goal": "test"})

    def test_host_browser_is_used_without_creating_another_session(self):
        supplied = Mock()
        supplied.observe.return_value = {"fingerprint": "observed", "actions": []}
        with patch.object(agent, "Browser", side_effect=AssertionError("unexpected browser")):
            instance = agent.Agent(None, "Read the page", browser=supplied)
        self.assertIs(instance.browser, supplied)
        supplied.observe.assert_called_once_with(screenshot=False)

    def test_uncertainty_remains_a_host_recovery_request_without_input(self):
        supplied = Mock()
        supplied.observe.return_value = {
            "fingerprint": "observed",
            "actions": [{"id": "click-1", "kind": "click", "node": 1, "label": "Continue"}],
        }
        supplied.fresh.return_value = True
        instance = agent.Agent(None, "Continue", browser=supplied)
        with patch.object(agent, "choose", return_value={"choice": "click-1", "confidence": 1, "target_confidence": 0.2}):
            result = instance.command("predict")
        self.assertEqual(result["decision"]["recover"], "uncertain")
        self.assertEqual(result["status"], "predicted")
        self.assertEqual(result["history"], [])
        supplied.act.assert_not_called()

    def test_uncertain_completion_audit_cannot_bypass_recovery_and_execute(self):
        for confidence, target_confidence in [(0.2, 1), (1, 0.2), (0.2, None)]:
            with self.subTest(confidence=confidence, target_confidence=target_confidence):
                supplied = Mock()
                supplied.observe.return_value = {
                    "fingerprint": "observed",
                    "actions": [{"id": "click-1", "kind": "click", "node": 1, "label": "Continue"}],
                }
                supplied.fresh.return_value = True
                instance = agent.Agent(None, "Continue", browser=supplied)
                audited = {"choice": "click-1", "confidence": confidence, "target_confidence": target_confidence}
                with (
                    patch.object(agent, "choose", return_value={"choice": "DONE", "confidence": 1}),
                    patch.object(agent, "review_completion", return_value=audited),
                ):
                    result = instance.command("predict")
                self.assertEqual(result["decision"]["recover"], "uncertain")
                with self.assertRaisesRegex(ValueError, "Recovery required"):
                    instance.command("act", {"fingerprint": "observed"})
                self.assertEqual(result["history"], [])
                supplied.act.assert_not_called()

    def test_confident_completion_audit_can_finish_without_recovery(self):
        supplied = Mock()
        supplied.observe.return_value = {"fingerprint": "observed", "actions": []}
        supplied.fresh.return_value = True
        instance = agent.Agent(None, "Read the page", browser=supplied)
        with (
            patch.object(agent, "choose", return_value={"choice": "DONE", "confidence": 1}),
            patch.object(agent, "review_completion", return_value={"choice": "DONE", "confidence": 1}),
        ):
            result = instance.command("tick")
        self.assertEqual(result["status"], "done")
        supplied.act.assert_not_called()


if __name__ == "__main__":
    unittest.main()
