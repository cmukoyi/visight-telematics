from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.services import hive_service as hs

UTC = timezone.utc


class TestTemporalCoherenceHelpers:
    def test_pairwise_temporal_eval_separates_display_and_coherent_diameter(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        positions = [
            ("tag-a", 51.5000, -0.1000, now),
            ("tag-b", 51.5001, -0.1001, now + timedelta(seconds=30)),
            ("tag-c", 52.0000, 0.5000, now + timedelta(minutes=20)),
        ]

        display_diameter_m, coherent_diameter_m, outlier_id, coherent_pairs, incoherent_pairs, max_pair_dt_s = hs.pairwise_temporal_eval(
            positions,
            threshold_m=500.0,
            coherence_window_s=5 * 60,
        )

        assert display_diameter_m is not None and display_diameter_m > 50_000
        assert coherent_diameter_m is not None and coherent_diameter_m < 100
        assert outlier_id is None
        assert coherent_pairs == 1
        assert incoherent_pairs == 2
        assert max_pair_dt_s == 20 * 60

    def test_pairwise_temporal_eval_picks_coherent_outlier_only_from_coherent_pairs(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        positions = [
            ("tag-a", 51.5000, -0.1000, now),
            ("tag-b", 51.5200, -0.1000, now + timedelta(seconds=20)),
            ("tag-c", 51.5001, -0.1001, now + timedelta(minutes=15)),
        ]

        display_diameter_m, coherent_diameter_m, outlier_id, coherent_pairs, incoherent_pairs, _ = hs.pairwise_temporal_eval(
            positions,
            threshold_m=500.0,
            coherence_window_s=5 * 60,
        )

        assert display_diameter_m is not None and coherent_diameter_m is not None
        assert coherent_diameter_m > 2_000
        assert outlier_id in {"tag-a", "tag-b"}
        assert coherent_pairs == 1
        assert incoherent_pairs == 2

    def test_snapshot_fingerprint_is_stable_for_reordered_positions(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        positions_a = [
            ("tag-b", 51.5001, -0.1001, now + timedelta(seconds=5)),
            ("tag-a", 51.5000, -0.1000, now),
        ]
        positions_b = list(reversed(positions_a))

        assert hs._snapshot_fingerprint(positions_a) == hs._snapshot_fingerprint(positions_b)

    def test_positions_payload_serializes_uuid_tag_ids(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        positions = [
            (uuid.uuid4(), 51.5000, -0.1000, now),
            (uuid.uuid4(), 51.5001, -0.1001, now + timedelta(seconds=10)),
        ]

        payload = hs._positions_used_payload(positions)
        encoded = json.dumps(payload)

        assert isinstance(encoded, str)
        assert all(isinstance(item["tag_id"], str) for item in payload)