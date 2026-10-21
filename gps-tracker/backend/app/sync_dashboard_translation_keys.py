#!/usr/bin/env python3
"""Idempotently seed customer-dashboard keys from its i18n-marked HTML.

Run after deployment for a tenant:
    docker exec visight_telematics_backend python app/sync_dashboard_translation_keys.py

The dashboard itself is the source of truth for the key inventory. This avoids
the historical failure mode where markup gains a data-i18n key but a separate,
manually maintained seed script omits it.
"""
from __future__ import annotations

import argparse
import re
import json
import os
from html import unescape
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MARKER_PATTERN = re.compile(
    r'<(?P<tag>[a-zA-Z][^>]*?)\sdata-i18n(?P<kind>-placeholder|-title)?="(?P<key>[^"]+)"(?P<tail>[^>]*)>(?P<text>.*?)</[^>]+>',
    re.DOTALL,
)
RUNTIME_CALL_PATTERN = re.compile(
    r"\bt(?:Alert|Confirm|Prompt)?\(\s*['\"](?P<key>[a-z][a-z0-9_.]+)['\"]\s*,\s*['\"](?P<text>(?:\\.|[^'\"])*)['\"]"
)
ATTRIBUTE_PATTERN = re.compile(r'\b(?P<name>placeholder|title)="(?P<value>[^"]*)"')
TAG_PATTERN = re.compile(r"<[^>]+>")
EXPLICIT_DEFAULTS = {
    "alerts.delete_tag_failed": ("Failed to delete tag", "Customer dashboard alert"),
    "alerts.reset_failed": ("Reset failed", "Customer dashboard alert"),
    "common.beta": ("Beta", "Customer dashboard UI"),
    "confirm.delete_selected_tags": ("Permanently delete selected tags? This cannot be undone.", "Customer dashboard confirmation"),
    "confirm.delete_tag": ("Delete tag? This cannot be undone.", "Customer dashboard confirmation"),
    "confirm.reset_password_for_user": ("Reset password for user? A new temporary password will be generated and shown once.", "Customer dashboard confirmation"),
    "confirm.sign_out_of_brand": ("Are you sure you want to sign out?", "Customer dashboard confirmation"),
    "tooltips.clear_all_plotted_alert_markers": ("Clear all plotted alert markers", "Customer dashboard title"),
    "tooltips.show_hide_geofences_on_the_map": ("Show / hide geofences on the map", "Customer dashboard title"),
    "auth.password_reset_share_message": ("Password reset details", "Customer dashboard prompt"),
}


def customer_dashboard_path(filename: str) -> Path:
    script_path = Path(__file__).resolve()
    candidates = (
        script_path.parents[2] / "customer-dashboard/public" / filename,
        script_path.parents[1] / "customer-dashboard/public" / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Customer dashboard source '{filename}' was not found. Checked: "
        + ", ".join(str(candidate) for candidate in candidates)
    )


def dashboard_path() -> Path:
    return customer_dashboard_path("index.html")


def extract_defaults(content: str) -> dict[str, tuple[str, str]]:
    defaults: dict[str, tuple[str, str]] = {}
    for match in MARKER_PATTERN.finditer(content):
        key = match.group("key")
        kind = match.group("kind")
        tail = match.group("tail")
        if kind:
            attribute_name = kind[1:]
            attribute_match = re.search(rf'\b{attribute_name}="([^"]*)"', tail)
            text = attribute_match.group(1) if attribute_match else ""
            context = f"Customer dashboard {attribute_name}"
        else:
            text = TAG_PATTERN.sub("", match.group("text")).strip()
            context = "Customer dashboard UI"

        if text and not text.startswith("${"):
            defaults.setdefault(key, (text, context))
    for match in RUNTIME_CALL_PATTERN.finditer(content):
        text = match.group("text").replace("\\n", "\n")
        if text:
            defaults.setdefault(match.group("key"), (text, "Customer dashboard runtime message"))
    defaults.update({key: value for key, value in EXPLICIT_DEFAULTS.items() if key not in defaults})
    return defaults


def clean_translation_text(value: str) -> str:
    return unescape(str(value or "")).replace("\u00a0", " ").strip()


def matches_default_translation(translated_text: str, default_text: str) -> bool:
    normalize = lambda value: " ".join(clean_translation_text(value).split()).casefold()
    return normalize(translated_text) == normalize(default_text)


def incomplete_translation_keys(session, defaults: dict[str, tuple[str, str]], language_code: str) -> list[str]:
    translations = {
        translation.key: clean_translation_text(translation.translated_text)
        for translation in session.query(Translation).filter(
            Translation.language_code == language_code
        ).all()
    }
    return [
        key
        for key, (_default_text, _context) in defaults.items()
        if not translations.get(key)
        or translations[key] == key
    ]


def translate_batch(texts: list[str], target_lang: str) -> list[str]:
    """Translate up to 100 dashboard strings with Azure Translator."""
    endpoint = os.getenv("AZURE_TRANSLATOR_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("AZURE_TRANSLATOR_KEY", "")
    region = os.getenv("AZURE_TRANSLATOR_REGION", "")
    if not endpoint or not api_key:
        raise RuntimeError(
            "Azure Translator is required for dashboard sync. Set "
            "AZURE_TRANSLATOR_ENDPOINT and AZURE_TRANSLATOR_KEY in backend/.env."
        )

    query = urlencode({"api-version": "3.0", "from": "en", "to": target_lang})
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Ocp-Apim-Subscription-Key": api_key,
    }
    if region:
        headers["Ocp-Apim-Subscription-Region"] = region
    request = Request(
        f"{endpoint}/translate?{query}",
        data=json.dumps([{"text": text} for text in texts]).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    translations = [
        clean_translation_text(item["translations"][0]["text"])
        for item in payload
    ]
    if len(translations) != len(texts) or any(not text for text in translations):
        raise RuntimeError("Azure Translator returned an incomplete translation batch.")
    return translations


def sync_translations(session, defaults: dict[str, tuple[str, str]], language_codes: set[str] | None = None) -> dict[str, int]:
    languages = session.query(Language).filter(Language.is_active == True).all()
    if language_codes:
        languages = [language for language in languages if language.code in language_codes]
    stats = {"created": 0, "updated": 0, "cleaned": 0, "failed": 0}

    for language in languages:
        code = language.code
        pending = []
        for key, (default_text, _context) in defaults.items():
            existing = session.query(Translation).filter(
                Translation.language_code == code,
                Translation.key == key,
            ).first()
            current_text = clean_translation_text(existing.translated_text) if existing else ""
            if code == "en" or not existing or not current_text or current_text == key:
                pending.append((key, default_text, existing))

        print(f"{code}: {len(pending)} translation(s) needed")
        for start in range(0, len(pending), 100):
            batch = pending[start:start + 100]
            source_texts = [clean_translation_text(default_text) for _key, default_text, _existing in batch]
            translated_texts = source_texts if code == "en" else translate_batch(source_texts, code)
            for (key, _default_text, existing), translated in zip(batch, translated_texts):
                if existing:
                    if existing.translated_text != translated:
                        existing.translated_text = translated
                        stats["updated"] += 1
                else:
                    session.add(Translation(language_code=code, key=key, translated_text=translated))
                    stats["created"] += 1
            session.commit()
            print(f"{code}: {min(start + len(batch), len(pending))}/{len(pending)} processed")

    return stats


def main() -> None:
    global Language, Translation, TranslationKey
    from app.database import SessionLocal
    from app.models_i18n import Language, Translation, TranslationKey

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--language",
        action="append",
        dest="languages",
        help="Synchronize only this active language; repeat for multiple languages.",
    )
    args = parser.parse_args()

    content = dashboard_path().read_text(encoding="utf-8")
    defaults = extract_defaults(content)
    marker_keys = set(re.findall(r'data-i18n(?:-placeholder|-title)?="([^"]+)"', content))
    runtime_keys = set(match.group("key") for match in RUNTIME_CALL_PATTERN.finditer(content))
    missing_defaults = sorted((marker_keys | runtime_keys) - set(defaults))
    if missing_defaults:
        raise RuntimeError(
            "Missing English defaults for dashboard i18n keys: " + ", ".join(missing_defaults)
        )
    session = SessionLocal()
    try:
        existing = {
            key for (key,) in session.query(TranslationKey.key)
            .filter(TranslationKey.key.in_(defaults))
            .all()
        }
        new_keys = [
            TranslationKey(
                key=key,
                category=key.split(".", 1)[0],
                default_text=text,
                context=context,
            )
            for key, (text, context) in defaults.items()
            if key not in existing
        ]
        session.add_all(new_keys)
        translation_stats = sync_translations(session, defaults, set(args.languages) if args.languages else None)
        session.commit()
        target_languages = session.query(Language).filter(Language.is_active == True)
        if args.languages:
            target_languages = target_languages.filter(Language.code.in_(args.languages))
        incomplete_by_language = {
            language.code: incomplete_translation_keys(session, defaults, language.code)
            for language in target_languages.filter(Language.code != "en").all()
        }
        incomplete_by_language = {
            code: keys for code, keys in incomplete_by_language.items() if keys
        }
        print(
            f"Dashboard i18n keys: {len(defaults)} found, {len(new_keys)} created, {len(existing)} already present; "
            f"translations created={translation_stats['created']} updated={translation_stats['updated']} "
            f"cleaned={translation_stats['cleaned']} failed={translation_stats['failed']}"
        )
        if incomplete_by_language:
            details = "; ".join(
                f"{code}: {len(keys)} incomplete ({', '.join(keys[:20])})"
                for code, keys in incomplete_by_language.items()
            )
            raise RuntimeError(f"Dashboard translation sync incomplete: {details}")
    finally:
        session.close()


if __name__ == "__main__":
    main()