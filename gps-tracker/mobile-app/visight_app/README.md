# ViSight Track mobile app

iOS and Android app for customer-dashboard users: Home | Map view | Trips | Assets
(designs in `UIDesigns/Mobile`).

- **Sign in** with the customer-dashboard email and password (`POST /api/auth/login`). There's no
  registration in the app: users are created in the customer dashboard.
- **Vehicles** come from the public API (`/api/v2/...`), which scopes every answer to the user's
  security group. Administrators, and roles with "See vehicles in all security groups", see every vehicle.
- **Every user sees all four tabs.** When a role doesn't include a feature (e.g. Trips needs "Trips and routes",
  live follow needs "Follow a vehicle live"), the tab says so instead of showing data.

## Run

```bash
flutter pub get
flutter run                                                     # production API
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8001     # local backend from the Android emulator
flutter test
```

## Layout

| Path | What |
| --- | --- |
| `lib/api/` | HTTP client (bearer token, 401/403 handling) and response models |
| `lib/session.dart` | Signed-in user, their vehicles, the selected vehicle and tab |
| `lib/screens/` | Login, the four tabs, trip detail (route replay) and vehicle detail |
| `lib/widgets/` | Header, markers, cards and shared actions (share location, replay latest trip) |
