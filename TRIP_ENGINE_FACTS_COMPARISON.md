# Trip Engine Facts: YOUR DEFINITIONS vs ACTUAL IMPLEMENTATION

**Date**: 2026-07-13  
**Comparison**: User-defined facts vs implemented trip_engine.py

---

## ⚠️ CRITICAL MISALIGNMENTS FOUND

### 1. **Trip Start** ❌ MISMATCH

#### Your Definition:
> "Start - when a last position is further than 100m away. that becomes a start"

#### Actual Implementation:
```python
# Lines 963-995 in trip_engine.py
if self.context.current_state == "STATIONARY":
    anchor_dist = haversine_distance(
        self.context.anchor_lat, self.context.anchor_lng,
        lat, lng
    )
    
    if anchor_dist > self.config.anchor_radius_m:  # 100m
        # Beyond R: Enter MOVE
        # Create stationary record FIRST
        stationary = self._create_stationary(self.context.anchor_points)
        
        # Enter MOVE state
        self.context.current_state = "MOVE"
        self.context.leg_buffer = [
            (start_lat, start_lng, start_time, start_pos_id),  # From anchor
            (lat, lng, observed_at, position_id)  # Current point
        ]
```

**Reality**: 
- ✅ Trip start DOES occur when position > 100m from anchor
- ✅ But it creates a STATIONARY first (from accumulated anchor points)
- ✅ Then enters MOVE state and starts accumulating leg buffer
- ⚠️ **Leg is NOT emitted immediately** - must meet move_confirm (150m) and min_leg_distance (300m)

---

### 2. **Stationary** ⚠️ PARTIAL MISMATCH

#### Your Definition:
> "stationary - if a tag has been in same place distance < 100m for 20min and over its stationary"

#### Actual Implementation:
```python
# Lines 510-520 in trip_engine.py
def _create_stationary(self, points, reason=""):
    # Calculate duration
    duration_seconds = (ended_at - started_at).total_seconds()
    
    # Journey grouping: Check if this stationary breaks the journey
    breaks_journey = duration_seconds > (self.config.journey_break_dwell_min * 60)  # 30 min
    
    if breaks_journey and self.context.current_journey_id:
        logger.info("Journey break detected (stationary %.0f min > threshold %.0f min)")
        self._close_journey()
```

**Reality**:
- ✅ Stationary IS defined as points < 100m apart (anchor_radius_m)
- ❌ **NO 20-minute minimum duration requirement** for creating a stationary
- ✅ Stationary CAN be any duration (even 1 second if points qualify)
- ✅ BUT: 30-minute dwell (not 20 min) determines journey breaks

**Geometry-Based, NOT Time-Based**:
```python
# Lines 1010-1030: Detection is purely geometric
if len(self.context.leg_buffer) >= 3:
    last_3 = self.context.leg_buffer[-3:]
    d12 = haversine_distance(...)
    d23 = haversine_distance(...)
    d13 = haversine_distance(...)
    
    if d12 <= 100m and d23 <= 100m and d13 <= 100m:
        # New stationary formed → close leg
```

---

### 3. **Leg** ❌ MAJOR MISMATCH

#### Your Definition:
> "leg. 2 coordinates connected are defined as legs point a point b point c is leg 1 leg 2 leg 3"

#### Actual Implementation:
```python
# Lines 603-650 in trip_engine.py
def _create_leg(self, leg_buffer, is_air_leg=False):
    if len(leg_buffer) < 2:
        return None
    
    # Calculate total distance
    total_distance_m = 0.0
    for i in range(len(leg_buffer) - 1):
        p1 = leg_buffer[i]
        p2 = leg_buffer[i + 1]
        total_distance_m += haversine_distance(p1[0], p1[1], p2[0], p2[1])
    
    # Filter: Move confirmation (must travel at least 150m)
    if total_distance_m < self.config.move_confirm_m:
        return None  # Discarded
    
    # Filter: Min leg distance (must be >= 300m for ground legs)
    if not is_air_leg and total_distance_m < self.config.min_leg_distance_m:
        return None  # Discarded as drift
```

**Reality**:
- ❌ **A leg is NOT just "2 coordinates connected"**
- ✅ A leg is **a polyline of MANY positions** accumulated during MOVE state
- ✅ Leg contains ALL GPS points between two stationaries
- ✅ Minimum 2 points, but typically 10-100+ points
- ✅ Must travel ≥ 150m to be emitted (move_confirm_m)
- ✅ Must travel ≥ 300m to avoid drift rejection (min_leg_distance_m)

**From Spec (PinPlot_Trip_Engine_Spec_v2.md Section 2.2)**:
> "A run of displacing points between two Stationaries (a polyline of many positions)"

**Example**:
```
Point A (10:00) → stationary
Point B (10:05) → moving, 50m away
Point C (10:07) → moving, 100m away
Point D (10:10) → moving, 200m away
Point E (10:15) → moving, 350m away
Point F (10:20) → moving, 400m away
Point G (10:25) → stationary (within 100m of H and I)
Point H (10:27) → stationary
Point I (10:30) → stationary

Leg 1 = [A, B, C, D, E, F] (all points from 10:00-10:20)
Stationary = [G, H, I] (10:25-10:30)
```

---

### 4. **Trip End** ✅ MOSTLY CORRECT

#### Your Definition:
> "trip end - positions are within 100m for over 30min allows for trip end"

#### Actual Implementation:
```python
# Lines 510-520 in trip_engine.py
breaks_journey = duration_seconds > (self.config.journey_break_dwell_min * 60)  # 30 min

if breaks_journey and self.context.current_journey_id:
    logger.info("Journey break detected")
    self._close_journey()
```

**Reality**:
- ✅ Trip (Journey) DOES end when stationary > 30 minutes
- ✅ "positions within 100m" = stationary by definition
- ✅ 30-minute threshold is correct (journey_break_dwell_min)
- ✅ Journey gets closed, next movement starts new journey

---

## 📊 SUMMARY TABLE

| Concept | Your Definition | Actual Implementation | Match? |
|---------|----------------|----------------------|--------|
| **Trip Start** | Position > 100m from last | Position > 100m from anchor → MOVE state | ⚠️ Partial (creates stationary first) |
| **Stationary** | < 100m for 20+ min | < 100m (geometry-based), NO minimum time | ❌ No time requirement |
| **Leg** | 2 coordinates = 1 leg | Polyline of MANY points, ≥150m, ≥300m filters | ❌ Major difference |
| **Trip End** | < 100m for 30+ min | Stationary > 30 min breaks journey | ✅ Correct |

---

## 🔧 CONFIGURATION VALUES (trip_engine.py)

```python
DEFAULT_ANCHOR_RADIUS_M = 100          # Stationary detection radius
DEFAULT_MIN_LEG_DISTANCE_M = 300       # Minimum leg distance (drift filter)
DEFAULT_MOVE_CONFIRM_M = 150           # Minimum distance before emitting leg
DEFAULT_MAX_SPEED_KMH = 200            # Outlier gate (air leg detection)
DEFAULT_GAP_TIMEOUT_MIN = 30           # Force close leg on gap
DEFAULT_JOURNEY_BREAK_DWELL_MIN = 30   # Journey break threshold
```

---

## 🎯 KEY ARCHITECTURAL POINTS

### State Machine (from spec):
```
STATIONARY ↔ MOVE

STATIONARY:
  - Points within 100m → roll anchor centroid
  - Beyond 100m → enter MOVE (leg opens)

MOVE:
  - Accumulate points in leg buffer
  - Last 3 points within 100m → close leg, create stationary
  - Gap timeout (30 min) → force close leg
```

### Geometry-Based (NOT Time-Based):
- Stationary detection: purely geometric (3 points within 100m)
- NO minimum duration for stationary
- Time only matters for journey breaks (30 min)

### Leg Composition:
- A leg is a **polyline of many GPS positions**
- NOT individual point-to-point segments
- Minimum 2 points, typically 10-100+ points
- Must meet distance thresholds (150m move confirm, 300m min distance)

---

## ✅ WHAT'S CORRECT IN YOUR UNDERSTANDING

1. ✅ 100m radius for stationary detection
2. ✅ 30-minute dwell ends a trip/journey
3. ✅ Distance-based state transitions

## ❌ WHAT NEEDS CORRECTION

1. ❌ Legs are NOT individual point-to-point connections
2. ❌ No 20-minute minimum for stationary (geometry-based only)
3. ❌ Leg emission requires 150m minimum (move_confirm)
4. ❌ Ground legs require 300m minimum (drift filter)

---

## 🚀 RECOMMENDATION

**Your understanding of "leg" needs the most correction**. The trip engine creates:
- **Stationaries**: Clusters of points < 100m apart (no time minimum)
- **Legs**: Collections of ALL movement points between stationaries (≥150m, ≥300m)
- **Journeys**: Groups of legs/stationaries until 30-minute dwell break

This matches the spec from `PinPlot_Trip_Engine_Spec_v2.md` that you verified earlier as "perfect match".
