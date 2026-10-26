"""Reference data for seed_demo: South African long-haul routes, places, trucks, drivers and staff.

Coordinates follow the national roads (N3 Durban–Johannesburg, N1 Johannesburg–Cape Town,
N2 Cape Town–Gqeberha–East London–Durban, N10 Gqeberha–Colesberg); waypoints are towns and
interchanges on the road, so tracks drawn between them follow the real route closely.
"""

PROVINCE = {"KZN": "KwaZulu-Natal", "GP": "Gauteng", "WC": "Western Cape", "EC": "Eastern Cape", "FS": "Free State",
            "NC": "Northern Cape"}

# Place: (name, group, city, lat, lng, radius m, road, suburb, town, postal code, province key)
PLACES = [
    # Depots
    ("Utrack Durban Depot (Bayhead)", "Depots", "DBN", -29.8805, 31.0245, 250, "12 Bayhead Road", "Bayhead", "Durban", "4026", "KZN"),
    ("Utrack Johannesburg Hub (City Deep)", "Depots", "JHB", -26.2305, 28.0745, 300, "41 Heidelberg Road", "City Deep", "Johannesburg", "2049", "GP"),
    ("Utrack Cape Town Depot (Epping)", "Depots", "CPT", -33.9285, 18.5455, 250, "7 Bofors Circle", "Epping Industria", "Cape Town", "7460", "WC"),
    # Customers
    ("Toyota SA – Prospecton Plant", "Customers", "DBN", -29.9690, 30.9330, 400, "Toyota Boulevard", "Prospecton", "Durban", "4110", "KZN"),
    ("Durban Container Terminal (Pier 2)", "Customers", "DBN", -29.8665, 31.0330, 350, "Langeberg Road", "Point", "Durban", "4001", "KZN"),
    ("Pick n Pay DC Longmeadow", "Customers", "JHB", -26.0845, 28.1385, 350, "Longmeadow Business Estate", "Edenvale", "Johannesburg", "1609", "GP"),
    ("Coca-Cola Beverages SA Wadeville", "Customers", "JHB", -26.2610, 28.1820, 300, "Nagington Road", "Wadeville", "Germiston", "1422", "GP"),
    ("Pick n Pay DC Philippi", "Customers", "CPT", -34.0005, 18.5650, 350, "Stock Road", "Philippi", "Cape Town", "7785", "WC"),
    ("Cape Town Container Terminal", "Customers", "CPT", -33.9085, 18.4405, 350, "Duncan Road", "Foreshore", "Cape Town", "8001", "WC"),
    ("Volkswagen Kariega Plant", "Customers", "PE", -33.7645, 25.4020, 450, "Algoa Road", "Kariega", "Kariega", "6229", "EC"),
    ("Port of Ngqura", "Customers", "PE", -33.8020, 25.6870, 400, "Ngqura Port Road", "Coega", "Gqeberha", "6100", "EC"),
    ("Mercedes-Benz SA East London Plant", "Customers", "EL", -33.0205, 27.8960, 400, "Settlers Way", "West Bank", "East London", "5201", "EC"),
    ("East London Port", "Customers", "EL", -33.0245, 27.9085, 300, "Bank Street", "West Bank", "East London", "5201", "EC"),
    ("Clover Bloemfontein", "Customers", "BFN", -29.1265, 26.2240, 300, "Harvey Road", "Hamilton", "Bloemfontein", "9301", "FS"),
    ("Bloemfontein Fresh Produce Market", "Customers", "BFN", -29.1290, 26.1920, 250, "Kenneth Kaunda Road", "Hilton", "Bloemfontein", "9301", "FS"),
    # Truck stops (rest and overnight stops)
    ("Shell Ultra City Mooi River", "Truck stops", None, -29.2280, 29.9870, 200, "N3 Toll Route", "Mooi River", "Mooi River", "3300", "KZN"),
    ("Engen 1-Stop Harrismith", "Truck stops", None, -28.2780, 29.1180, 250, "N3", "Harrismith", "Harrismith", "9880", "FS"),
    ("Engen 1-Stop Kroonstad", "Truck stops", None, -27.6260, 27.2340, 200, "N1", "Kroonstad", "Kroonstad", "9499", "FS"),
    ("Shell Ultra City Bloemfontein", "Truck stops", None, -29.0530, 26.2500, 200, "N1", "Bloemfontein North", "Bloemfontein", "9301", "FS"),
    ("Engen Colesberg Truck Stop", "Truck stops", None, -30.7200, 25.1000, 250, "N1", "Colesberg", "Colesberg", "9795", "NC"),
    ("Total Three Sisters Truck Stop", "Truck stops", None, -31.9010, 23.0800, 250, "N1", "Three Sisters", "Beaufort West", "6970", "WC"),
    ("Engen Laingsburg", "Truck stops", None, -33.1960, 20.8590, 200, "N1", "Laingsburg", "Laingsburg", "6900", "WC"),
    ("Shell Swellendam", "Truck stops", None, -34.0220, 20.4430, 200, "N2", "Swellendam", "Swellendam", "6740", "WC"),
    ("Engen Mossel Bay", "Truck stops", None, -34.1630, 22.0870, 200, "N2", "Voorbaai", "Mossel Bay", "6506", "WC"),
    ("Shell Humansdorp", "Truck stops", None, -34.0285, 24.7690, 200, "N2", "Humansdorp", "Humansdorp", "6300", "EC"),
    ("Engen Mthatha", "Truck stops", None, -31.5920, 28.7650, 200, "N2", "Mthatha", "Mthatha", "5099", "EC"),
    ("Shell Kokstad", "Truck stops", None, -30.5480, 29.4270, 200, "N2", "Kokstad", "Kokstad", "4700", "KZN"),
    ("Engen Cradock", "Truck stops", None, -32.1690, 25.6180, 200, "N10", "Cradock", "Cradock", "5880", "EC"),
]
PLACE_GROUPS = {"Depots": "#2563eb", "Customers": "#16a34a", "Truck stops": "#f59e0b"}

# Roads between city gates (lat, lng); a leg runs place → gate → road → gate → place
ROADS = {
    ("DBN", "JHB"): [(-29.86, 30.98), (-29.82, 30.86), (-29.72, 30.62), (-29.60, 30.38), (-29.43, 30.20), (-29.2280, 29.9870),
                     (-29.01, 29.87), (-28.75, 29.62), (-28.37, 29.38), (-28.2780, 29.1180), (-27.85, 28.96), (-27.50, 28.75),
                     (-27.03, 28.60), (-26.75, 28.45), (-26.50, 28.36), (-26.27, 28.12)],
    ("JHB", "BFN"): [(-26.27, 28.00), (-26.45, 27.85), (-26.70, 27.80), (-27.20, 27.45), (-27.6260, 27.2340), (-28.05, 27.10),
                     (-28.52, 27.01), (-29.0530, 26.2500), (-29.10, 26.21)],
    ("BFN", "CPT"): [(-29.10, 26.21), (-29.40, 25.95), (-29.80, 25.65), (-30.72, 25.10), (-31.05, 24.50), (-31.41, 23.94),
                     (-31.9010, 23.0800), (-32.35, 22.58), (-32.65, 21.90), (-33.1960, 20.8590), (-33.34, 20.03), (-33.55, 19.70),
                     (-33.64, 19.45), (-33.73, 19.00), (-33.88, 18.62)],
    ("CPT", "PE"):  [(-33.95, 18.62), (-34.08, 18.85), (-34.17, 19.10), (-34.23, 19.43), (-34.12, 19.90), (-34.0220, 20.4430),
                     (-34.09, 21.26), (-34.18, 21.75), (-34.1630, 22.0870), (-33.96, 22.46), (-34.04, 23.05), (-34.05, 23.37),
                     (-33.98, 23.90), (-34.0285, 24.7690), (-33.95, 25.15), (-33.83, 25.55)],
    ("PE", "EL"):   [(-33.83, 25.65), (-33.70, 26.00), (-33.52, 26.30), (-33.31, 26.53), (-33.10, 26.90), (-32.88, 27.40), (-33.00, 27.85)],
    ("EL", "DBN"):  [(-32.98, 27.85), (-32.70, 27.95), (-32.30, 28.15), (-31.95, 28.45), (-31.5920, 28.7650), (-31.30, 29.05),
                     (-30.95, 29.25), (-30.5480, 29.4270), (-30.70, 29.90), (-30.74, 30.45), (-30.48, 30.65), (-30.29, 30.75),
                     (-30.05, 30.88), (-29.92, 30.95)],
    ("PE", "BFN"):  [(-33.83, 25.62), (-33.40, 25.75), (-32.85, 25.65), (-32.1690, 25.6180), (-31.49, 25.01), (-30.72, 25.10),
                     (-29.80, 25.65), (-29.40, 25.95), (-29.10, 26.21)],
}
ROAD_NAMES = {("DBN", "JHB"): "N3", ("JHB", "BFN"): "N1", ("BFN", "CPT"): "N1", ("JHB", "CPT"): "N1", ("CPT", "PE"): "N2",
              ("PE", "EL"): "N2", ("EL", "DBN"): "N2", ("PE", "BFN"): "N10"}
# JHB–CPT is JHB–BFN then BFN–CPT (overnight at Colesberg)
ROADS[("JHB", "CPT")] = ROADS[("JHB", "BFN")] + ROADS[("BFN", "CPT")][1:]
# Climbs and passes (slower): Van Reenen's Pass, Hex River Pass, Kei River / Transkei hills
SLOW = [(-28.37, 29.38, 25), (-33.45, 19.85, 20), (-32.60, 28.05, 30), (-31.30, 29.05, 25)]
# Coastal and Highveld altitude, roughly
INLAND = lambda lat, lng: 1350 if (lat > -32.6 and 23.0 < lng < 29.5) else 180

# Trucks: (key, description, make, model, year, registration, vehicle group, L/100 km, odometer km at the start,
#          licence renewed this many days before the run: the Volvo's expires in 18 days, the MAN's expired 6 days ago)
TRUCKS = [
    ("volvo", "UT01 Volvo FH16 750", "Volvo", "FH16 750 Globetrotter XL", "2022", "ND 452-118", "N3 Corridor", "37.8", 386_420, 347),
    ("scania", "UT02 Scania R 560", "Scania", "R 560 Highline", "2021", "LJ 47 XK GP", "N1 Corridor", "35.6", 472_890, 238),
    ("actros", "UT03 Mercedes-Benz Actros 2645", "Mercedes-Benz", "Actros 2645 LS", "2023", "CA 718-342", "Coastal N2", "34.2", 211_340, 130),
    ("man", "UT04 MAN TGX 26.540", "MAN", "TGX 26.540 XLX", "2020", "ND 873-560", "Coastal N2", "36.4", 538_700, 371),
    ("daf", "UT05 DAF XF 530", "DAF", "XF 530 Space Cab", "2022", "HZ 21 PB GP", "Regional", "33.9", 302_150, 270),
]
VEHICLE_GROUPS = {"N3 Corridor": ("#2563eb", "KZN Operations"), "Coastal N2": ("#0891b2", "KZN Operations"),
                  "N1 Corridor": ("#7c3aed", "Inland Operations"), "Regional": ("#ea580c", "Inland Operations")}

# The lanes each truck runs, repeated (city → city)
LANES = {
    "volvo": ["DBN", "JHB", "DBN"],
    "scania": ["JHB", "CPT", "JHB"],
    "actros": ["CPT", "PE", "EL", "DBN", "JHB", "CPT"],
    "man": ["DBN", "EL", "PE", "EL", "DBN"],
    "daf": ["JHB", "BFN", "PE", "BFN", "JHB"],
}
HOME = {"volvo": "DBN", "scania": "JHB", "actros": "CPT", "man": "DBN", "daf": "JHB"}

# Drivers: (first, last, employee no., key code, phone, truck they mostly drive, style: careful | normal | heavy-footed)
DRIVERS = [
    ("Sipho", "Dlamini", "UT-1042", "B7F3C2D10001", "+27 82 514 7730", "volvo", "careful"),
    ("Johan", "Botha", "UT-1017", "B7F3C2D10002", "+27 83 290 4411", "scania", "normal"),
    ("Thabo", "Nkosi", "UT-1088", "B7F3C2D10003", "+27 71 662 0985", "actros", "careful"),
    ("Mandla", "Mthembu", "UT-1053", "B7F3C2D10004", "+27 76 118 3402", "man", "heavy-footed"),
    ("Pieter", "Joubert", "UT-1029", "B7F3C2D10005", "+27 82 903 5528", "daf", "normal"),
    ("Bongani", "Khumalo", "UT-1101", "B7F3C2D10006", "+27 73 445 8810", None, "normal"),       # relief driver
    ("Andile", "Mahlangu", "UT-1115", "B7F3C2D10007", "+27 61 207 3346", None, "heavy-footed"),  # relief driver
]

EMAIL_DOMAIN = "utracklogistics.co.za"
# Staff: (first, last, title, role(s), security group or None = all vehicles)
STAFF = [
    ("Thandi", "Mokoena", "Fleet Manager", ["Fleet Manager"], None),
    ("Pieter", "van der Merwe", "Workshop Manager", ["Maintenance User"], None),
    ("Ayesha", "Patel", "Finance Manager", ["Reporting User"], None),
    ("Sibusiso", "Ndlovu", "Control Room Operator", ["Operator"], "KZN Operations"),
    ("Lerato", "Molefe", "Control Room Operator", ["Operator"], "Inland Operations"),
]
FLEET_MANAGER_PERMISSIONS = [
    "map.view", "live.track", "history.view", "events.view", "places.view", "places.manage", "places.arm", "inbox.view",
    "rules.manage", "reports.view", "reports.schedule", "reports.design", "analytics.manage", "maintenance.view",
    "maintenance.manage", "breakdowns.log", "vehicles.manage", "vehicle_groups.manage", "users.view", "security.all_vehicles",
]
