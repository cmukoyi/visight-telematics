"""Teltonika → ViSight Track dictionary.

IO_ELEMENTS  what each Teltonika AVL IO ID means (FMB/FMC family): name,
             unit, scaling and value labels, used to show readable values.
EVENTS       our own event codes. Every decoded AVL record is classified
             into one of them from its event IO ID and IO values; trips are
             built from these codes, not from raw Teltonika IDs.
CATEGORIES   what a package can show or hide (TagPackage.allowed_event_types);
             each event code belongs to exactly one category.

Sources: Teltonika "Data Sending Parameters ID" wiki pages for FMB/FMC
devices, checked against packets from an FMC125 (trip start 250=1, periodic
event 0, trip stop 250=0).
"""
from typing import Optional

# ---------------------------------------------------------------------------
# IO elements: id → (key, name, unit, scale, value labels)
# value shown = raw * scale (when scale is set); labels map raw values.
# ---------------------------------------------------------------------------

_ON_OFF = {0: "Off", 1: "On"}

IO_ELEMENTS: dict[int, tuple] = {
    1:   ("din1", "Digital input 1", None, None, _ON_OFF),
    2:   ("din2", "Digital input 2", None, None, _ON_OFF),
    3:   ("din3", "Digital input 3", None, None, _ON_OFF),
    9:   ("ain1", "Analog input 1", "V", 0.001, None),
    11:  ("iccid1", "SIM ICCID (part 1)", None, None, None),
    12:  ("fuel_used_gps", "Fuel used (GPS)", "l", 0.001, None),
    13:  ("fuel_rate_gps", "Fuel rate (GPS)", "l/100km", 0.01, None),
    14:  ("iccid2", "SIM ICCID (part 2)", None, None, None),
    15:  ("eco_score", "Eco score", None, 0.01, None),
    16:  ("total_odometer", "Total odometer", "km", 0.001, None),
    17:  ("axis_x", "Accelerometer X", "mG", None, None),
    18:  ("axis_y", "Accelerometer Y", "mG", None, None),
    19:  ("axis_z", "Accelerometer Z", "mG", None, None),
    21:  ("gsm_signal", "GSM signal", "/5", None, None),
    24:  ("speed", "Speed", "km/h", None, None),
    66:  ("external_voltage", "External voltage", "V", 0.001, None),
    67:  ("battery_voltage", "Battery voltage", "V", 0.001, None),
    68:  ("battery_current", "Battery current", "A", 0.001, None),
    69:  ("gnss_status", "GNSS status", None, None,
          {0: "Off", 1: "On, with fix", 2: "On, no fix", 3: "Sleep"}),
    72:  ("dallas_temp1", "Dallas temperature 1", "°C", 0.1, None),
    73:  ("dallas_temp2", "Dallas temperature 2", "°C", 0.1, None),
    74:  ("dallas_temp3", "Dallas temperature 3", "°C", 0.1, None),
    75:  ("dallas_temp4", "Dallas temperature 4", "°C", 0.1, None),
    78:  ("ibutton", "iButton ID", None, None, None),
    80:  ("data_mode", "Data mode", None, None,
          {0: "Home, stopped", 1: "Home, moving", 2: "Roaming, stopped",
           3: "Roaming, moving", 4: "Unknown, stopped", 5: "Unknown, moving"}),
    113: ("battery_level", "Battery level", "%", None, None),
    179: ("dout1", "Digital output 1", None, None, _ON_OFF),
    180: ("dout2", "Digital output 2", None, None, _ON_OFF),
    181: ("gnss_pdop", "GNSS PDOP", None, 0.1, None),
    182: ("gnss_hdop", "GNSS HDOP", None, 0.1, None),
    199: ("trip_odometer", "Trip odometer", "km", 0.001, None),
    200: ("sleep_mode", "Sleep mode", None, None,
          {0: "No sleep", 1: "GPS sleep", 2: "Deep sleep", 3: "Online sleep", 4: "Ultra sleep"}),
    205: ("gsm_cell_id", "GSM cell ID", None, None, None),
    206: ("gsm_area_code", "GSM area code", None, None, None),
    236: ("alarm", "Alarm", None, None, {0: "Reserved", 1: "Alarm"}),
    237: ("network_type", "Network type", None, None,
          {0: "3G", 1: "GSM", 2: "4G", 3: "LTE Cat M1", 4: "LTE Cat NB1", 99: "Unknown"}),
    238: ("user_id", "User ID", None, None, None),
    239: ("ignition", "Ignition", None, None, _ON_OFF),
    240: ("movement", "Movement", None, None, _ON_OFF),
    241: ("gsm_operator", "Active GSM operator", None, None, None),
    243: ("green_driving_duration", "Green driving event duration", "ms", None, None),
    246: ("towing", "Towing", None, None, {0: "Steady", 1: "Towing"}),
    247: ("crash", "Crash detection", None, None, None),
    248: ("immobilizer", "Immobilizer", None, None, None),
    249: ("jamming", "GNSS jamming", None, None, {0: "Stopped", 1: "Jamming"}),
    250: ("trip", "Trip", None, None, {0: "Stop", 1: "Start"}),
    251: ("idling", "Idling", None, None, {0: "Moving", 1: "Idling"}),
    252: ("unplug", "Unplug", None, None, {0: "Power present", 1: "Unplugged"}),
    253: ("green_driving_type", "Green driving type", None, None,
          {1: "Harsh acceleration", 2: "Harsh braking", 3: "Harsh cornering"}),
    254: ("green_driving_value", "Green driving value", "g", 0.01, None),
    255: ("over_speeding", "Over speeding", "km/h", None, None),
}
for _zone in range(1, 21):  # 155–174: geofence zones 1–20
    IO_ELEMENTS[154 + _zone] = (f"geofence_zone_{_zone}", f"Geofence zone {_zone}", None, None,
                                {0: "Exited", 1: "Entered"})
IO_ELEMENTS[175] = ("auto_geofence", "Auto geofence", None, None, {0: "Exited", 1: "Entered"})

IO_ODOMETER = 16
IO_TRIP_ODOMETER = 199
IO_IGNITION = 239
IO_MOVEMENT = 240


def io_value(io: dict, io_id: int):
    """Raw IO value from a dict keyed by int or str (JSON round-trips keys to str)."""
    if io_id in io:
        return io[io_id]
    return io.get(str(io_id))


_DECIMALS = {0.1: 1, 0.01: 2, 0.001: 3}


def describe_io(io: dict) -> list[dict]:
    """Readable IO elements: [{id, key, name, value, display}], known IDs first."""
    out = []
    for raw_key, raw in (io or {}).items():
        io_id = int(raw_key)
        meta = IO_ELEMENTS.get(io_id)
        if not meta:
            out.append({"id": io_id, "key": f"io_{io_id}", "name": f"IO {io_id}", "value": raw, "display": str(raw)})
            continue
        key, name, unit, scale, labels = meta
        if labels and isinstance(raw, int) and raw in labels:
            display = labels[raw]
        elif scale and isinstance(raw, (int, float)):
            value = raw * scale
            display = f"{value:.{_DECIMALS.get(scale, 0)}f}" + (f" {unit}" if unit else "")
        else:
            display = f"{raw} {unit}" if unit else str(raw)
        out.append({"id": io_id, "key": key, "name": name, "value": raw, "display": display})
    out.sort(key=lambda x: (x["id"] not in IO_ELEMENTS, x["id"]))
    return out


# ---------------------------------------------------------------------------
# Our events
# code → (label, category, kind)
#   kind: trip (bounds a trip) · position · alert (driver/vehicle behaviour) · info
# ---------------------------------------------------------------------------

EVENTS: dict[str, tuple[str, str, str]] = {
    "trip_start":         ("Trip start",            "trip",               "trip"),
    "trip_end":           ("Trip end",              "trip",               "trip"),
    "position":           ("Position (driving)",    "position",           "position"),
    "parked_position":    ("Position (parked)",     "position",           "position"),
    "ignition_on":        ("Ignition on",           "ignition",           "info"),
    "ignition_off":       ("Ignition off",          "ignition",           "info"),
    "movement_start":     ("Movement start",        "movement",           "info"),
    "movement_stop":      ("Movement stop",         "movement",           "info"),
    "idling_start":       ("Idling start",          "idling",             "alert"),
    "idling_end":         ("Idling end",            "idling",             "info"),
    "overspeed":          ("Speeding",              "overspeed",          "alert"),
    "harsh_acceleration": ("Harsh acceleration",    "harsh_acceleration", "alert"),
    "harsh_braking":      ("Harsh braking",         "harsh_braking",      "alert"),
    "harsh_cornering":    ("Harsh cornering",       "harsh_cornering",    "alert"),
    "crash":              ("Crash detected",        "crash",              "alert"),
    "towing":             ("Towing",                "towing",             "alert"),
    "power_cut":          ("External power cut",    "power_cut",          "alert"),
    "power_restored":     ("External power restored", "power_cut",        "info"),
    "gnss_jamming":       ("GNSS jamming",          "gnss_jamming",       "alert"),
    "gnss_jamming_end":   ("GNSS jamming ended",    "gnss_jamming",       "info"),
    "geofence_enter":     ("Geofence entered",      "geofence",           "info"),
    "geofence_exit":      ("Geofence exited",       "geofence",           "info"),
    "panic":              ("Alarm / panic",         "panic",              "alert"),
    "digital_input":      ("Digital input change",  "digital_input",      "info"),
}

# What in the Teltonika record produces each event (shown in the admin Dictionary).
EVENT_SOURCES: dict[str, str] = {
    "trip_start": "Event IO 250 (Trip) = 1",
    "trip_end": "Event IO 250 (Trip) = 0",
    "position": "Event ID 0 (periodic record), ignition IO 239 = 1",
    "parked_position": "Event ID 0 (periodic record), ignition IO 239 = 0",
    "ignition_on": "Event IO 239 (Ignition) = 1",
    "ignition_off": "Event IO 239 (Ignition) = 0",
    "movement_start": "Event IO 240 (Movement) = 1",
    "movement_stop": "Event IO 240 (Movement) = 0",
    "idling_start": "Event IO 251 (Idling) = 1",
    "idling_end": "Event IO 251 (Idling) = 0",
    "overspeed": "Event IO 255 (Over speeding), value = speed in km/h",
    "harsh_acceleration": "Event IO 253 (Green driving type) = 1, IO 254 = g ×100",
    "harsh_braking": "Event IO 253 (Green driving type) = 2, IO 254 = g ×100",
    "harsh_cornering": "Event IO 253 (Green driving type) = 3, IO 254 = g ×100",
    # Some firmware sends the green driving record with event IO 243 (duration)
    # or 254 (value) instead; the type in IO 253 still says which one it is.
    "crash": "Event IO 247 (Crash detection) > 0",
    "towing": "Event IO 246 (Towing) = 1",
    "power_cut": "Event IO 252 (Unplug) = 1",
    "power_restored": "Event IO 252 (Unplug) = 0",
    "gnss_jamming": "Event IO 249 (Jamming) = 1",
    "gnss_jamming_end": "Event IO 249 (Jamming) = 0",
    "geofence_enter": "Event IO 155–174 (Geofence zone 1–20) or 175 (Auto geofence) = 1",
    "geofence_exit": "Event IO 155–174 (Geofence zone 1–20) or 175 (Auto geofence) = 0",
    "panic": "Event IO 236 (Alarm)",
    "digital_input": "Event IO 1–3 (Digital input 1–3)",
}

CATEGORIES: list[dict] = [
    {"key": "trip",               "label": "Trip start / end"},
    {"key": "position",           "label": "Position updates"},
    {"key": "ignition",           "label": "Ignition on/off"},
    {"key": "movement",           "label": "Movement start/stop"},
    {"key": "idling",             "label": "Excessive idling"},
    {"key": "overspeed",          "label": "Speeding"},
    {"key": "harsh_acceleration", "label": "Harsh acceleration"},
    {"key": "harsh_braking",      "label": "Harsh braking"},
    {"key": "harsh_cornering",    "label": "Harsh cornering"},
    {"key": "crash",              "label": "Crash detection"},
    {"key": "towing",             "label": "Towing detection"},
    {"key": "power_cut",          "label": "External power disconnected"},
    {"key": "gnss_jamming",       "label": "GNSS jamming"},
    {"key": "geofence",           "label": "Geofence (device-side)"},
    {"key": "panic",              "label": "Alarm / panic"},
    {"key": "digital_input",      "label": "Digital input change"},
]
CATEGORY_KEYS = {c["key"] for c in CATEGORIES}

_GREEN_DRIVING = {1: "harsh_acceleration", 2: "harsh_braking", 3: "harsh_cornering"}
_GREEN_DRIVING_IOS = (253, 254, 243)  # type, value, duration: each can be the record's event IO
_ON_OFF_EVENTS = {
    239: ("ignition_off", "ignition_on"),
    240: ("movement_stop", "movement_start"),
    250: ("trip_end", "trip_start"),
    251: ("idling_end", "idling_start"),
    252: ("power_restored", "power_cut"),
    249: ("gnss_jamming_end", "gnss_jamming"),
}


def classify(event_io_id: int, io: dict) -> Optional[str]:
    """Our event code for an AVL record, or None if the event ID has no mapping."""
    if event_io_id == 0:
        ignition = io_value(io, IO_IGNITION)
        moving = ignition == 1 or (ignition is None and io_value(io, IO_MOVEMENT) == 1)
        return "position" if moving else "parked_position"
    value = io_value(io, event_io_id)
    if event_io_id in _ON_OFF_EVENTS:
        off_code, on_code = _ON_OFF_EVENTS[event_io_id]
        return on_code if value == 1 else off_code if value == 0 else None
    if event_io_id in _GREEN_DRIVING_IOS:
        return _GREEN_DRIVING.get(io_value(io, 253))
    if event_io_id == 255:
        return "overspeed"
    if event_io_id == 247:
        return "crash" if value else None
    if event_io_id == 246:
        return "towing" if value == 1 else None
    if 155 <= event_io_id <= 175:
        return "geofence_enter" if value == 1 else "geofence_exit"
    if event_io_id == 236:
        return "panic"
    if event_io_id in (1, 2, 3):
        return "digital_input"
    return None


def category_of(code: Optional[str]) -> Optional[str]:
    return EVENTS[code][1] if code in EVENTS else None


def event_label(code: Optional[str], event_io_id: int = 0) -> str:
    """Our event's label; for a record we don't classify, the name of its event IO."""
    if code in EVENTS:
        return EVENTS[code][0]
    if event_io_id in IO_ELEMENTS:
        return IO_ELEMENTS[event_io_id][1]
    return f"Unmapped (IO {event_io_id})"
