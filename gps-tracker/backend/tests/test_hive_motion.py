"""Unit tests for HIVE motion-awareness service (Phase 3, spec v1.1).

These tests exercise the pure-Python state machine without any DB or
network: we feed lightweight stand-ins for HiveLiveState / HiveConfigVersion
/ HiveTagMembership so the logic can be validated in isolation. This keeps
the suite fast and runnable in CI without Postgres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.services import hive_motion as hm
from app.models import HiveMotionState

UTC = timezone.utc


# ─── lightweight test doubles ───────────────────────────────────────────────

@dataclass
class FakeCfg:
    motion_speed_threshold_kmh: Optional[float] = 5.0
    motion_settling_time_s: int = 300
    coherence_speed_tol_kmh: float = 10.0
    coherence_bearing_tol_deg: float = 45.0


@dataclass
class FakeLive:
    motion_state: str = HiveMotionState.STATIONARY.value
    motion_state_since: Optional[datetime] = None
    pending_motion_change_since: Optional[datetime] = None
    centroid_lat: Optional[float] = None
    centroid_lng: Optional[float] = None
    centroid_speed_kmh: Optional[float] = None
    centroid_bearing_deg: Optional[float] = None
    centroid_anchor_lat: Optional[float] = None
    centroid_anchor_lng: Optional[float] = None
    centroid_anchor_at: Optional[datetime] = None


@dataclass
class FakeMembership:
    tag_id: str = "tag-1"
    velocity_speed_kmh: Optional[float] = None
    velocity_bearing_deg: Optional[float] = None
    velocity_computed_at: Optional[datetime] = None
    previous_lat: Optional[float] = None
    previous_lng: Optional[float] = None
    previous_seen_at: Optional[datetime] = None


# ─── geometry helpers ───────────────────────────────────────────────────────

class TestGeometry:
    def test_haversine_known_distance(self):
        # London ↔ Paris ≈ 343 km
        d = hm._haversine_m(51.5074, -0.1278, 48.8566, 2.3522)
        assert 340_000 < d < 350_000

    def test_bearing_due_east(self):
        # Same latitude, easterly target → bearing ≈ 90°
        b = hm._bearing_deg(0.0, 0.0, 0.0, 1.0)
        assert 89.5 < b < 90.5

    def test_bearing_delta_wraparound(self):
        # 350° vs 10° = 20°, not 340°
        assert hm._bearing_delta_deg(350.0, 10.0) == pytest.approx(20.0)
        assert hm._bearing_delta_deg(10.0, 350.0) == pytest.approx(20.0)


# ─── centroid + velocity ────────────────────────────────────────────────────

class TestCentroid:
    def test_empty_returns_none(self):
        assert hm.compute_centroid([]) is None

    def test_single_position(self):
        c = hm.compute_centroid([("t1", 51.5, -0.1)])
        assert c == (51.5, -0.1)

    def test_geometric_mean_of_three(self):
        c = hm.compute_centroid([
            ("t1", 50.0, 0.0),
            ("t2", 51.0, 1.0),
            ("t3", 52.0, 2.0),
        ])
        assert c == pytest.approx((51.0, 1.0))


class TestCentroidVelocity:
    def test_no_anchor_returns_zero(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        v = hm.compute_centroid_velocity((51.5, -0.1), now, None, None, None)
        assert v.speed_kmh == 0.0
        assert v.bearing_deg is None

    def test_anchor_too_fresh_returns_zero(self):
        # Less than 30s of baseline isn't a meaningful velocity sample.
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        v = hm.compute_centroid_velocity(
            (51.5001, -0.1), now,
            51.5, -0.1, now - timedelta(seconds=10),
        )
        assert v.speed_kmh == 0.0

    def test_speed_from_anchor(self):
        # 1 km north over 60 seconds ≈ 60 km/h
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        v = hm.compute_centroid_velocity(
            (51.509, 0.0), now,
            51.500, 0.0, now - timedelta(seconds=60),
        )
        assert 55 < v.speed_kmh < 65
        assert v.bearing_deg is not None and 0 <= v.bearing_deg < 5  # ≈ due north


# ─── per-tag velocity ────────────────────────────────────────────────────────

class TestUpdateTagVelocity:
    def test_first_observation_no_velocity(self):
        m = FakeMembership()
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        result = hm.update_tag_velocity(m, 51.5, -0.1, now, now)
        # No previous anchor → can't compute velocity; only seeds anchor.
        assert result is None
        assert m.previous_lat == 51.5
        assert m.previous_seen_at == now

    def test_subsequent_observation_computes_velocity(self):
        now0 = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        now1 = now0 + timedelta(seconds=60)
        m = FakeMembership(previous_lat=51.500, previous_lng=0.0,
                           previous_seen_at=now0)
        result = hm.update_tag_velocity(m, 51.509, 0.0, now1, now1)
        assert result is not None
        assert 55 < result.speed_kmh < 65
        # Anchor advanced to the latest report.
        assert m.previous_seen_at == now1

    def test_duplicate_timestamp_is_ignored(self):
        # Out-of-order or duplicate reports must not mutate the velocity.
        now0 = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        m = FakeMembership(previous_lat=51.500, previous_lng=0.0,
                           previous_seen_at=now0)
        result = hm.update_tag_velocity(m, 51.501, 0.0, now0, now0)
        assert result is None


# ─── coherence score ────────────────────────────────────────────────────────

class TestCoherenceScore:
    def _v(self, speed, bearing, t):
        return hm.TagVelocity("t", speed, bearing, t)

    def test_zero_centroid_speed_returns_zero(self):
        cfg = FakeCfg()
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        centroid_v = hm.CentroidVelocity(51.0, 0.0, 0.0, None)
        assert hm.coherence_score([self._v(10, 90, now)], centroid_v, cfg, now) == 0.0

    def test_all_coherent(self):
        cfg = FakeCfg()
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        centroid_v = hm.CentroidVelocity(51.0, 0.0, 30.0, 90.0)
        vs = [self._v(28, 88, now), self._v(32, 92, now), self._v(30, 90, now)]
        assert hm.coherence_score(vs, centroid_v, cfg, now) == pytest.approx(1.0)

    def test_half_coherent(self):
        cfg = FakeCfg()
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        centroid_v = hm.CentroidVelocity(51.0, 0.0, 30.0, 90.0)
        vs = [self._v(30, 90, now), self._v(5, 270, now)]  # one with, one against
        assert hm.coherence_score(vs, centroid_v, cfg, now) == pytest.approx(0.5)

    def test_stale_tags_excluded(self):
        cfg = FakeCfg()
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        centroid_v = hm.CentroidVelocity(51.0, 0.0, 30.0, 90.0)
        old = now - timedelta(seconds=hm.COHERENCE_TAG_HISTORY_SEC + 60)
        # Only the stale tag — excluded entirely → 0.0.
        assert hm.coherence_score([self._v(30, 90, old)], centroid_v, cfg, now) == 0.0


# ─── state machine ──────────────────────────────────────────────────────────

class TestMotionStateMachine:
    NOW = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    def _moving_centroid(self, speed=20.0, bearing=90.0):
        return hm.CentroidVelocity(51.0, 0.0, speed, bearing)

    def _still_centroid(self):
        return hm.CentroidVelocity(51.0, 0.0, 0.0, None)

    def test_disabled_profile_stays_stationary(self):
        live = FakeLive()
        cfg = FakeCfg(motion_speed_threshold_kmh=None)  # Stationary profile
        d = hm.evaluate_motion_state(live, cfg, self._moving_centroid(50, 90), 1.0, self.NOW)
        assert d.state == "STATIONARY"
        assert not d.suppress_proximity

    def test_stationary_to_pre_transit_requires_30s(self):
        live = FakeLive()
        cfg = FakeCfg()
        # First tick of motion: arms the pending timer but does NOT transition.
        d = hm.evaluate_motion_state(live, cfg, self._moving_centroid(), 0.5, self.NOW)
        assert d.state == "STATIONARY"
        assert live.pending_motion_change_since == self.NOW
        # 31 seconds of sustained motion → transition fires.
        later = self.NOW + timedelta(seconds=31)
        d2 = hm.evaluate_motion_state(live, cfg, self._moving_centroid(), 0.5, later)
        assert d2.state == "PRE_TRANSIT"
        assert d2.changed
        assert d2.suppress_proximity

    def test_pre_transit_to_in_transit_requires_120s_and_coherence(self):
        # Motion started at NOW; PRE_TRANSIT entered at NOW+30s.
        live = FakeLive(
            motion_state="PRE_TRANSIT",
            motion_state_since=self.NOW + timedelta(seconds=30),
            pending_motion_change_since=self.NOW,  # motion-start anchor preserved
        )
        cfg = FakeCfg()
        # At 119s coherent — not yet promoted.
        d = hm.evaluate_motion_state(
            live, cfg, self._moving_centroid(), 0.9,
            self.NOW + timedelta(seconds=119),
        )
        assert d.state == "PRE_TRANSIT"
        # At 121s coherent — promoted.
        d2 = hm.evaluate_motion_state(
            live, cfg, self._moving_centroid(), 0.9,
            self.NOW + timedelta(seconds=121),
        )
        assert d2.state == "IN_TRANSIT"
        assert d2.changed

    def test_pre_transit_to_in_transit_blocked_by_low_coherence(self):
        live = FakeLive(
            motion_state="PRE_TRANSIT",
            motion_state_since=self.NOW + timedelta(seconds=30),
            pending_motion_change_since=self.NOW,
        )
        cfg = FakeCfg()
        d = hm.evaluate_motion_state(
            live, cfg, self._moving_centroid(), 0.3,  # below 0.6 threshold
            self.NOW + timedelta(seconds=200),
        )
        assert d.state == "PRE_TRANSIT"

    def test_pre_transit_back_to_stationary_marks_fresh_eval(self):
        # Motion stops; we wait 30s in PRE_TRANSIT, then bail back.
        entered_at = self.NOW + timedelta(seconds=30)
        live = FakeLive(
            motion_state="PRE_TRANSIT",
            motion_state_since=entered_at,
            pending_motion_change_since=self.NOW,
        )
        cfg = FakeCfg()
        d = hm.evaluate_motion_state(
            live, cfg, self._still_centroid(), 0.0,
            entered_at + timedelta(seconds=31),
        )
        assert d.state == "STATIONARY"
        assert d.fresh_eval_required
        assert d.changed

    def test_in_transit_to_settling_after_3_min_stable(self):
        live = FakeLive(
            motion_state="IN_TRANSIT",
            motion_state_since=self.NOW,
        )
        cfg = FakeCfg()
        # Stopped, but only 60s — still IN_TRANSIT
        d = hm.evaluate_motion_state(live, cfg, self._still_centroid(), 0.0,
                                     self.NOW + timedelta(seconds=60))
        assert d.state == "IN_TRANSIT"
        # 181s stable → SETTLING
        d2 = hm.evaluate_motion_state(live, cfg, self._still_centroid(), 0.0,
                                      self.NOW + timedelta(seconds=181))
        assert d2.state == "SETTLING"

    def test_settling_to_in_transit_on_motion_resume(self):
        live = FakeLive(
            motion_state="SETTLING",
            motion_state_since=self.NOW,
        )
        cfg = FakeCfg()
        d = hm.evaluate_motion_state(live, cfg, self._moving_centroid(), 0.9,
                                     self.NOW + timedelta(seconds=30))
        assert d.state == "IN_TRANSIT"
        assert d.suppress_proximity

    def test_settling_to_stationary_after_settling_time(self):
        live = FakeLive(
            motion_state="SETTLING",
            motion_state_since=self.NOW,
        )
        cfg = FakeCfg(motion_settling_time_s=300)
        d = hm.evaluate_motion_state(live, cfg, self._still_centroid(), 0.0,
                                     self.NOW + timedelta(seconds=301))
        assert d.state == "STATIONARY"
        assert d.fresh_eval_required


# ─── centroid anchor refresh ────────────────────────────────────────────────

class TestCentroidAnchor:
    def test_seeds_when_missing(self):
        live = FakeLive()
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        hm.maybe_refresh_centroid_anchor(live, (51.5, -0.1), now)
        assert live.centroid_anchor_lat == 51.5
        assert live.centroid_anchor_at == now

    def test_no_op_when_fresh(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        live = FakeLive(centroid_anchor_lat=51.0, centroid_anchor_lng=0.0,
                        centroid_anchor_at=now - timedelta(seconds=60))
        hm.maybe_refresh_centroid_anchor(live, (52.0, 1.0), now)
        # Anchor unchanged because it's only 60s old (< 300s window).
        assert live.centroid_anchor_lat == 51.0

    def test_rolls_when_window_elapsed(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        live = FakeLive(centroid_anchor_lat=51.0, centroid_anchor_lng=0.0,
                        centroid_anchor_at=now - timedelta(seconds=400))
        hm.maybe_refresh_centroid_anchor(live, (52.0, 1.0), now)
        assert live.centroid_anchor_lat == 52.0
        assert live.centroid_anchor_at == now
