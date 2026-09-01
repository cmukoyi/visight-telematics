#!/usr/bin/env python3
"""Idempotently seed customer-dashboard keys from its i18n-marked HTML.

Run after deployment for a tenant:
    docker exec pinplot_backend python app/sync_dashboard_translation_keys.py

The dashboard itself is the source of truth for the key inventory. This avoids
the historical failure mode where markup gains a data-i18n key but a separate,
manually maintained seed script omits it.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.database import SessionLocal
from app.models_i18n import TranslationKey


MARKER_PATTERN = re.compile(
    r'<(?P<tag>[a-zA-Z][^>]*?)\sdata-i18n(?P<kind>-placeholder|-title)?="(?P<key>[^"]+)"(?P<tail>[^>]*)>(?P<text>.*?)</[^>]+>',
    re.DOTALL,
)
RUNTIME_CALL_PATTERN = re.compile(
    r"\bt(?:Alert|Confirm|Prompt)?\(\s*['\"](?P<key>[a-z][a-z0-9_.]+)['\"]\s*,\s*['\"](?P<text>(?:\\.|[^'\"])*)['\"]"
)
QR_TRANSLATION_PATTERN = re.compile(r'"(?P<key>qr\.[a-z0-9_]+)":\s*"(?P<text>[^"]+)"')
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
    "floor_plan.address_optional": ("Address (optional)", "Customer dashboard placeholder"),
    "floor_plan.esp32_gateway_hint": ("ESP32S3 gateway MAC address", "Customer dashboard UI"),
    "floor_plan.floor_number": ("Floor number (0 = ground, 1 = first, -1 = basement)", "Customer dashboard placeholder"),
    "labels.gateway_name": ("Gateway Name", "Customer dashboard UI"),
    "tooltips.clear_all_plotted_alert_markers": ("Clear all plotted alert markers", "Customer dashboard title"),
    "tooltips.show_hide_geofences_on_the_map": ("Show / hide geofences on the map", "Customer dashboard title"),
    "auth.password_reset_share_message": ("Password reset details", "Customer dashboard prompt"),
}


def dashboard_path() -> Path:
    return Path(__file__).resolve().parents[2] / "customer-dashboard/public/index.html"


def qr_generator_path() -> Path:
    return Path(__file__).resolve().parents[2] / "customer-dashboard/public/qr-generator.html"


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


def extract_qr_defaults(content: str) -> dict[str, tuple[str, str]]:
    return {
        match.group("key"): (match.group("text"), "QR/NFC generator UI")
        for match in QR_TRANSLATION_PATTERN.finditer(content)
    }


def main() -> None:
    content = dashboard_path().read_text(encoding="utf-8")
    defaults = extract_defaults(content)
    qr_defaults = extract_qr_defaults(qr_generator_path().read_text(encoding="utf-8"))
    defaults.update(qr_defaults)
    marker_keys = set(re.findall(r'data-i18n(?:-placeholder|-title)?="([^"]+)"', content))
    runtime_keys = set(match.group("key") for match in RUNTIME_CALL_PATTERN.finditer(content))
    missing_defaults = sorted(marker_keys | runtime_keys - set(defaults))
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
        session.commit()
        print(f"Dashboard i18n keys: {len(defaults)} found, {len(new_keys)} created, {len(existing)} already present")
    finally:
        session.close()


if __name__ == "__main__":
    main()