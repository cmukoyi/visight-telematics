#!/usr/bin/env python3
"""Verify that a deployed dashboard language has no missing English fallbacks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from app.sync_dashboard_translation_keys import (
    dashboard_path,
    extract_defaults,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://pinplot.me")
    parser.add_argument("--language", default="fr")
    parser.add_argument("--translations-file", type=Path)
    args = parser.parse_args()

    defaults = extract_defaults(dashboard_path().read_text(encoding="utf-8"))
    if args.translations_file:
        translations = json.loads(args.translations_file.read_text(encoding="utf-8"))
    else:
        try:
            with urlopen(f"{args.base_url.rstrip('/')}/api/translations/{args.language}", timeout=20) as response:
                translations = json.loads(response.read().decode("utf-8"))
        except URLError as error:
            print(f"Unable to fetch {args.language} translations: {error}", file=sys.stderr)
            return 2

    incomplete = [
        key
        for key, (_default_text, _context) in defaults.items()
        if not translations.get(key)
        or translations[key] == key
    ]
    print(f"{args.language} dashboard translations: {len(defaults) - len(incomplete)}/{len(defaults)}")
    if not incomplete:
        return 0

    print(f"Incomplete keys ({len(incomplete)}): {', '.join(sorted(incomplete))}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())