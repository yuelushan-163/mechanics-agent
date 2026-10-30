from __future__ import annotations

import unittest

from mechanics_agent.debug_logs import DebugLogStore, redact_text, redact_value


class DebugLogTests(unittest.TestCase):
    def test_nested_secrets_and_token_text_are_redacted(self) -> None:
        store = DebugLogStore()
        store.add(
            level="error",
            message="Authorization: Bearer hidden-token",
            details={
                "api_key": "key-value",
                "nested": {
                    "password": "password-value",
                    "message": "request used sk-supersecrettoken",
                },
            },
        )

        entry = store.list()[0]

        self.assertNotIn("hidden-token", str(entry))
        self.assertNotIn("key-value", str(entry))
        self.assertNotIn("password-value", str(entry))
        self.assertNotIn("supersecrettoken", str(entry))
        self.assertEqual("[REDACTED]", entry["details"]["api_key"])
        self.assertEqual("[REDACTED]", entry["details"]["nested"]["password"])

    def test_sequence_is_monotonic_after_clear(self) -> None:
        store = DebugLogStore()
        first = store.add(level="INFO", message="first")
        self.assertEqual(1, store.clear())
        second = store.add(level="INFO", message="second")
        self.assertGreater(second.sequence, first.sequence)

    def test_redaction_helpers_keep_non_sensitive_values(self) -> None:
        self.assertEqual("ordinary text", redact_text("ordinary text"))
        self.assertEqual({"mesh_size": 5}, redact_value({"mesh_size": 5}))


if __name__ == "__main__":
    unittest.main()
