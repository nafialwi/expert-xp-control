from __future__ import annotations

import unittest

from xp_next.capability_registry import (
    CapabilityState,
    LocalCapabilityRegistry,
)


class CapabilityRegistryTests(unittest.TestCase):
    def test_local_registry_is_deterministic_and_never_networks(self):
        paths = {
            "python": "/tools/python",
            "git": "/tools/git",
            "node": None,
        }

        def which(name: str):
            return paths.get(name)

        calls: list[tuple[str, str]] = []

        def probe(name: str, executable: str) -> str:
            calls.append((name, executable))
            return {
                "python": "Python 3.14.6",
                "git": "git version 2.51.0",
            }[name]

        registry = LocalCapabilityRegistry(which=which, version_probe=probe)
        snapshot = registry.snapshot()

        self.assertEqual(snapshot["python"]["state"], CapabilityState.READY.value)
        self.assertEqual(snapshot["git"]["state"], CapabilityState.READY.value)
        self.assertEqual(snapshot["node"]["state"], CapabilityState.UNAVAILABLE.value)
        self.assertFalse(snapshot["python"]["network_used"])
        self.assertFalse(snapshot["git"]["network_used"])
        self.assertFalse(snapshot["node"]["network_used"])
        self.assertEqual(calls, [("python", "/tools/python"), ("git", "/tools/git")])

    def test_found_binary_with_failed_probe_needs_attention(self):
        def which(name: str):
            return f"/tools/{name}"

        def probe(name: str, executable: str) -> str:
            if name == "git":
                raise RuntimeError("probe failed")
            return "ok"

        snapshot = LocalCapabilityRegistry(
            which=which,
            version_probe=probe,
        ).snapshot()

        self.assertEqual(snapshot["git"]["state"], CapabilityState.NEEDS_ATTENTION.value)
        self.assertEqual(snapshot["git"]["version"], None)
        self.assertFalse(snapshot["git"]["network_used"])

    def test_snapshot_has_only_initial_local_foundation_capabilities(self):
        snapshot = LocalCapabilityRegistry(
            which=lambda name: None,
            version_probe=lambda name, executable: "unused",
        ).snapshot()
        self.assertEqual(set(snapshot), {"python", "git", "node"})


if __name__ == "__main__":
    unittest.main()
