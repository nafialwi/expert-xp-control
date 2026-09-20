from __future__ import annotations

import unittest

from xp_next.capability_registry import CapabilityState, LocalCapabilityRegistry


class CapabilityPresenceTests(unittest.TestCase):
    def test_expanded_local_capabilities_are_presence_only_for_ai_worker(self):
        version_calls: list[str] = []

        def which(name: str):
            return {
                "python": "/bin/python",
                "git": "/bin/git",
                "node": "/bin/node",
            }.get(name)

        def version_probe(name: str, executable: str) -> str:
            version_calls.append(name)
            return f"{name} version"

        def presence(name: str):
            return {
                "local_qwen": "/models/qwen.gguf",
                "hermes": "/opt/hermes/hermes-agent",
            }.get(name)

        snapshot = LocalCapabilityRegistry(
            which=which,
            version_probe=version_probe,
            presence=presence,
            sqlite_version="3.50.0",
        ).snapshot()

        self.assertEqual(
            set(snapshot),
            {"python", "git", "node", "sqlite", "local_qwen", "hermes"},
        )
        self.assertEqual(snapshot["sqlite"]["state"], CapabilityState.READY.value)
        self.assertEqual(snapshot["local_qwen"]["state"], CapabilityState.AVAILABLE.value)
        self.assertEqual(snapshot["hermes"]["state"], CapabilityState.AVAILABLE.value)
        self.assertEqual(snapshot["local_qwen"]["version"], None)
        self.assertEqual(snapshot["hermes"]["version"], None)
        self.assertEqual(version_calls, ["python", "git", "node"])
        self.assertFalse(snapshot["local_qwen"]["network_used"])
        self.assertFalse(snapshot["hermes"]["network_used"])

    def test_presence_absence_does_not_claim_readiness(self):
        snapshot = LocalCapabilityRegistry(
            which=lambda name: None,
            version_probe=lambda name, executable: "unused",
            presence=lambda name: None,
            sqlite_version="3.50.0",
        ).snapshot()
        self.assertEqual(snapshot["local_qwen"]["state"], CapabilityState.UNAVAILABLE.value)
        self.assertEqual(snapshot["hermes"]["state"], CapabilityState.UNAVAILABLE.value)


if __name__ == "__main__":
    unittest.main()
