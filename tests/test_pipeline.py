import json
import unittest

import memory_pipeline as mp


class ValidatorTests(unittest.TestCase):
    def test_extraction_accepts_valid_schema(self):
        raw = json.dumps({
            "facts": [{
                "text": "API limit is 120 per minute.",
                "type": "world",
                "occurred_start": None,
                "occurred_end": None,
                "where": None,
                "entities": ["API"],
                "evidence": ["s0"],
            }]
        })
        ok, errors, _ = mp.validate_extraction(raw, {"s0"})
        self.assertTrue(ok, errors)

    def test_extraction_rejects_unknown_evidence(self):
        raw = json.dumps({
            "facts": [{
                "text": "API limit is 120 per minute.",
                "type": "world",
                "occurred_start": None,
                "occurred_end": None,
                "where": None,
                "entities": ["API"],
                "evidence": ["s9"],
            }]
        })
        ok, errors, _ = mp.validate_extraction(raw, {"s0"})
        self.assertFalse(ok)
        self.assertTrue(any("hallucinated evidence" in e for e in errors))

    def test_admission_revise_requires_replacement(self):
        raw = json.dumps({"0": {"decision": "revise", "evidence": ["s0"], "replacement": ""}})
        ok, errors, _ = mp.validate_admission(raw, {"s0"}, ["revise", "drop"])
        self.assertFalse(ok)
        self.assertTrue(any("replacement" in e for e in errors))

    def test_admission_accepts_correct_revise(self):
        raw = json.dumps({
            "0": {
                "decision": "revise",
                "evidence": ["s0"],
                "replacement": "The limit is 120.",
            }
        })
        ok, errors, decision = mp.validate_admission(raw, {"s0"}, ["revise", "drop"])
        self.assertTrue(ok, errors)
        self.assertEqual(decision, "revise")

    def test_admission_rejects_wrong_decision(self):
        raw = json.dumps({"0": {"decision": "pass", "evidence": ["s0"], "replacement": ""}})
        ok, errors, _ = mp.validate_admission(raw, {"s0"}, ["revise", "drop"])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
