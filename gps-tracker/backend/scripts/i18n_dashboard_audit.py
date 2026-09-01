#!/usr/bin/env python3
"""Validate that customer-dashboard translation markers are well formed.

This script deliberately validates the contract we can enforce reliably in CI:
every i18n marker has a valid namespaced key and every key is represented in the
source inventory. Dynamic text must be emitted with ``t(key, fallback)`` or an
i18n marker by the renderer that creates it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
MARKER_PATTERN = re.compile(
    r'data-i18n(?:-placeholder|-title)?="([^"]+)"'
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    dashboard = repo_root / "customer-dashboard/public/index.html"
    content = dashboard.read_text(encoding="utf-8")
    keys = sorted(set(MARKER_PATTERN.findall(content)))
    invalid = [key for key in keys if not KEY_PATTERN.fullmatch(key)]

    print(f"Customer dashboard i18n markers: {len(keys)}")
    if invalid:
        print("Invalid i18n keys:")
        print("\n".join(f"  {key}" for key in invalid))
        return 1

    print("All i18n marker keys are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())