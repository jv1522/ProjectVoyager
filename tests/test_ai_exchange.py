import json
import unittest

from voyager.ai_exchange import build_entry_brief, parse_ai_response


class AIExchangeTests(unittest.TestCase):
    def test_build_entry_brief_includes_entry_and_attachment_context(self):
        brief = build_entry_brief(
            7,
            {"day": "2026-11-25", "composition": "Leaving Earth"},
            ["practice.wav"],
        )

        self.assertEqual(brief["entry_id"], 7)
        self.assertEqual(brief["day"], "2026-11-25")
        self.assertEqual(brief["attachments"], ["practice.wav"])
        self.assertIn("Do not invent performance observations.", brief["request"])

    def test_parse_ai_response_returns_only_supported_string_fields(self):
        response = json.dumps(
            {
                "entry_id": 7,
                "composition": "Try a different strumming pattern.",
                "curriculum": 42,
                "reflection": "Suggestion only.",
                "notes": "Must not be applied.",
            }
        )

        self.assertEqual(
            parse_ai_response(response, 7),
            {
                "composition": "Try a different strumming pattern.",
                "reflection": "Suggestion only.",
            },
        )

    def test_parse_ai_response_rejects_non_object_and_wrong_entry(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            parse_ai_response("[]", 7)
        with self.assertRaisesRegex(ValueError, "selected entry ID"):
            parse_ai_response('{"entry_id": 8, "composition": "Idea"}', 7)
        with self.assertRaisesRegex(ValueError, "selected entry ID"):
            parse_ai_response('{"entry_id": true, "composition": "Idea"}', 1)

    def test_parse_ai_response_rejects_missing_suggestion_fields(self):
        with self.assertRaisesRegex(ValueError, "No supported fields"):
            parse_ai_response('{"entry_id": 7, "notes": "Not a suggestion"}', 7)


if __name__ == "__main__":
    unittest.main()
