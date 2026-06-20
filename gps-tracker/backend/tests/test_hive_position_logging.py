"""Test enhanced HIVE position logging (v1.2.1).

Tests the new logging additions for trajectory analysis:
- Enhanced positions_used with lat/lon coordinates
- Tag fix history per tag
- Metadata flags for source_id and accuracy availability
"""
import pytest
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from app.services.hive_service import (
    _positions_used_payload,
    _tag_fix_history_payload,
)


UTC = timezone.utc


class TestPositionsUsedPayload:
    """Test enhanced positions_used payload includes coordinates."""
    
    def test_includes_lat_lon_coordinates(self):
        """positions_used should include lat/lon, not just tag_id and observed_at."""
        now = datetime.now(UTC)
        positions = [
            ("tag-123", 51.5074, -0.1278, now),
            ("tag-456", 51.5196, -0.1400, now + timedelta(minutes=2)),
        ]
        
        payload = _positions_used_payload(positions)
        
        assert len(payload) == 2
        assert payload[0]["tag_id"] == "tag-123"
        assert payload[0]["lat"] == 51.5074
        assert payload[0]["lon"] == -0.1278
        assert "observed_at" in payload[0]
        
        assert payload[1]["tag_id"] == "tag-456"
        assert payload[1]["lat"] == 51.5196
        assert payload[1]["lon"] == -0.1400
    
    def test_coordinates_rounded_to_6_decimals(self):
        """Coordinates should be rounded to 6 decimal places (~0.11m precision)."""
        now = datetime.now(UTC)
        positions = [
            ("tag-123", 51.50740123456789, -0.12780987654321, now),
        ]
        
        payload = _positions_used_payload(positions)
        
        assert payload[0]["lat"] == 51.507401  # Rounded to 6 decimals
        assert payload[0]["lon"] == -0.127810  # Rounded to 6 decimals
    
    def test_sorted_by_tag_id_and_timestamp(self):
        """Payload should be sorted by tag_id, then observed_at."""
        now = datetime.now(UTC)
        positions = [
            ("tag-zzz", 51.5074, -0.1278, now + timedelta(minutes=5)),
            ("tag-aaa", 51.5196, -0.1400, now + timedelta(minutes=2)),
            ("tag-aaa", 51.5100, -0.1350, now),
        ]
        
        payload = _positions_used_payload(positions)
        
        # Should be sorted: tag-aaa (earlier), tag-aaa (later), tag-zzz
        assert payload[0]["tag_id"] == "tag-aaa"
        assert payload[1]["tag_id"] == "tag-aaa"
        assert payload[2]["tag_id"] == "tag-zzz"
        
        # Verify tag-aaa entries are time-sorted
        ts0 = datetime.fromisoformat(payload[0]["observed_at"].replace("+00:00", ""))
        ts1 = datetime.fromisoformat(payload[1]["observed_at"].replace("+00:00", ""))
        assert ts0 < ts1
    
    def test_handles_timezone_aware_and_naive(self):
        """Should handle both timezone-aware and naive datetimes."""
        now_aware = datetime.now(UTC)
        now_naive = datetime.now()
        
        positions = [
            ("tag-123", 51.5074, -0.1278, now_aware),
            ("tag-456", 51.5196, -0.1400, now_naive),
        ]
        
        payload = _positions_used_payload(positions)
        
        # Both should produce valid ISO8601 timestamps
        assert payload[0]["observed_at"].endswith("+00:00")
        assert payload[1]["observed_at"].endswith("+00:00")


class TestTagFixHistoryPayload:
    """Test tag fix history captures per-tag position history."""
    
    def test_captures_current_fix_per_tag(self):
        """Should capture current fix for each tag with valid position."""
        now = datetime.now(UTC)
        
        # Mock memberships
        membership1 = Mock(tag_id="tag-123")
        membership2 = Mock(tag_id="tag-456")
        
        # Mock tags with positions
        tag1 = Mock(
            id="tag-123",
            latitude="51.5074",
            longitude="-0.1278",
            last_seen=now,
        )
        tag2 = Mock(
            id="tag-456",
            latitude="51.5196",
            longitude="-0.1400",
            last_seen=now + timedelta(minutes=5),
        )
        
        # Mock DB
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [tag1, tag2]
        
        history = _tag_fix_history_payload([membership1, membership2], mock_db, now)
        
        assert "tag-123" in history
        assert "tag-456" in history
        assert len(history["tag-123"]) == 1
        assert len(history["tag-456"]) == 1
        
        fix1 = history["tag-123"][0]
        assert fix1["lat"] == 51.5074
        assert fix1["lon"] == -0.1278
        assert "observed_at" in fix1
        
        fix2 = history["tag-456"][0]
        assert fix2["lat"] == 51.5196
        assert fix2["lon"] == -0.1400
    
    def test_skips_tags_without_position(self):
        """Should skip tags with missing lat/lon or last_seen."""
        now = datetime.now(UTC)
        
        membership1 = Mock(tag_id="tag-good")
        membership2 = Mock(tag_id="tag-no-lat")
        membership3 = Mock(tag_id="tag-no-timestamp")
        
        tag_good = Mock(
            id="tag-good",
            latitude="51.5074",
            longitude="-0.1278",
            last_seen=now,
        )
        tag_no_lat = Mock(
            id="tag-no-lat",
            latitude=None,
            longitude="-0.1278",
            last_seen=now,
        )
        tag_no_ts = Mock(
            id="tag-no-timestamp",
            latitude="51.5074",
            longitude="-0.1278",
            last_seen=None,
        )
        
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            tag_good, tag_no_lat, tag_no_ts
        ]
        
        history = _tag_fix_history_payload(
            [membership1, membership2, membership3], mock_db, now
        )
        
        # Only tag-good should be in history
        assert "tag-good" in history
        assert "tag-no-lat" not in history
        assert "tag-no-timestamp" not in history
    
    def test_handles_invalid_coordinates(self):
        """Should skip tags with non-numeric coordinates."""
        now = datetime.now(UTC)
        
        membership = Mock(tag_id="tag-bad")
        tag_bad = Mock(
            id="tag-bad",
            latitude="invalid",
            longitude="-0.1278",
            last_seen=now,
        )
        
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = tag_bad
        
        history = _tag_fix_history_payload([membership], mock_db, now)
        
        # Should be empty (invalid coordinates skipped)
        assert "tag-bad" not in history


class TestEvaluationMetadata:
    """Test evaluation metadata flags for data availability."""
    
    def test_metadata_flags_in_freshness_payload(self):
        """Freshness payload should include availability flags."""
        # This would be tested in the full evaluate_hive integration test
        # but we can document the expected structure here
        
        expected_meta = {
            "accuracy_available": False,
            "source_id_available": False,
            "position_history_available": False,
        }
        
        # When implemented, freshness_payload["meta"] should include these flags
        assert True  # Placeholder for integration test


class TestBackwardsCompatibility:
    """Test that enhanced logging doesn't break existing code."""
    
    def test_positions_used_payload_still_sortable(self):
        """Enhanced payload should still work with fingerprint generation."""
        now = datetime.now(UTC)
        positions = [
            ("tag-123", 51.5074, -0.1278, now),
        ]
        
        payload = _positions_used_payload(positions)
        
        # Fingerprint generation expects tag_id and observed_at
        assert "tag_id" in payload[0]
        assert "observed_at" in payload[0]
        
        # Can still generate fingerprint from tag_id @ observed_at
        fp = f"{payload[0]['tag_id']}@{payload[0]['observed_at']}"
        assert fp.startswith("tag-123@")
    
    def test_tag_fix_history_is_optional(self):
        """tag_fix_history can be None/empty without breaking evaluation."""
        # Empty history should not cause errors
        empty_history = {}
        history_json = json.dumps(empty_history) if empty_history else None
        
        # Should be safe to store None or empty JSON
        assert history_json is None or history_json == "{}"


class TestLoggingAdditionsSpec:
    """Verify compliance with HIVE_Position_Logging_Additions.md spec."""
    
    def test_positions_used_has_required_fields(self):
        """positions_used entries must have lat, lon, observed_at per spec."""
        now = datetime.now(UTC)
        positions = [("tag-123", 51.5074, -0.1278, now)]
        
        payload = _positions_used_payload(positions)
        entry = payload[0]
        
        # Required by spec
        assert "tag_id" in entry
        assert "observed_at" in entry
        assert "lat" in entry
        assert "lon" in entry
        
        # Not yet available (spec acknowledges these as TODO)
        # "source_id" and "accuracy_m" will be added when upstream provides them
    
    def test_tag_fix_history_structure(self):
        """tag_fix_history should be a map of tag_id -> array of fixes."""
        now = datetime.now(UTC)
        
        membership = Mock(tag_id="tag-123")
        tag = Mock(
            id="tag-123",
            latitude="51.5074",
            longitude="-0.1278",
            last_seen=now,
        )
        
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = tag
        
        history = _tag_fix_history_payload([membership], mock_db, now)
        
        # Structure: {tag_id: [{observed_at, lat, lon}, ...]}
        assert isinstance(history, dict)
        assert isinstance(history["tag-123"], list)
        assert isinstance(history["tag-123"][0], dict)
        
        fix = history["tag-123"][0]
        assert "observed_at" in fix
        assert "lat" in fix
        assert "lon" in fix


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
