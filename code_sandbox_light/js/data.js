/**
 * Sample / Demo data — mirrors realistic Tracksolid Pro API responses.
 * Used in demo mode when no real API credentials are configured.
 */

const DEMO = {

  // ── Current user session ───────────────────────────────────
  currentUser: {
    account: "admin@pinplot.pro",
    name: "Admin User",
    role: "admin",
    avatar: null
  },

  // ── Asset categories (device groups) ──────────────────────
  categories: [
    { id: "grp_01", name: "Vehicles",    icon: "fa-car",          color: "#3B82F6", count: 4 },
    { id: "grp_02", name: "Equipment",   icon: "fa-toolbox",      color: "#F59E0B", count: 3 },
    { id: "grp_03", name: "Containers",  icon: "fa-box",          color: "#8B5CF6", count: 2 },
    { id: "grp_04", name: "Personnel",   icon: "fa-user-hard-hat",color: "#10B981", count: 2 }
  ],

  // ── Assets / Devices ──────────────────────────────────────
  assets: [
    {
      imei: "867004046512345",
      deviceName: "Truck Alpha-1",
      mcType: "AT4",
      groupId: "grp_01",
      status: "online",
      battery: 87,
      rfidTag: "RFID-A001",
      lat: 25.7617,
      lng: -80.1918,
      speed: 42,
      gpsTime: "2025-04-20 14:32:10",
      positionType: 5,
      address: "NW 2nd Ave, Miami, FL"
    },
    {
      imei: "867004046523456",
      deviceName: "Van Beta-2",
      mcType: "AT4",
      groupId: "grp_01",
      status: "online",
      battery: 64,
      rfidTag: "RFID-A002",
      lat: 25.7750,
      lng: -80.2082,
      speed: 0,
      gpsTime: "2025-04-20 14:30:55",
      positionType: 5,
      address: "Brickell Ave, Miami, FL"
    },
    {
      imei: "867004046534567",
      deviceName: "Sedan Gamma-3",
      mcType: "AT6",
      groupId: "grp_01",
      status: "idle",
      battery: 93,
      rfidTag: "RFID-A003",
      lat: 25.7489,
      lng: -80.2405,
      speed: 0,
      gpsTime: "2025-04-20 13:58:22",
      positionType: 5,
      address: "SW 8th St, Miami, FL"
    },
    {
      imei: "867004046545678",
      deviceName: "Pickup Delta-4",
      mcType: "AT4",
      groupId: "grp_01",
      status: "offline",
      battery: 12,
      rfidTag: "RFID-A004",
      lat: 25.7880,
      lng: -80.2110,
      speed: 0,
      gpsTime: "2025-04-20 09:14:00",
      positionType: 5,
      address: "NW 36th St, Miami, FL"
    },
    {
      imei: "867004046556789",
      deviceName: "Excavator E-1",
      mcType: "JM-VL03",
      groupId: "grp_02",
      status: "online",
      battery: 78,
      rfidTag: "RFID-B001",
      lat: 25.7955,
      lng: -80.2790,
      speed: 5,
      gpsTime: "2025-04-20 14:31:40",
      positionType: 1,
      address: "NW 87th Ave, Doral, FL"
    },
    {
      imei: "867004046567890",
      deviceName: "Generator G-2",
      mcType: "JM-VL03",
      groupId: "grp_02",
      status: "idle",
      battery: 55,
      rfidTag: "RFID-B002",
      lat: 25.8210,
      lng: -80.2640,
      speed: 0,
      gpsTime: "2025-04-20 12:00:00",
      positionType: 1,
      address: "Miami Lakes, FL"
    },
    {
      imei: "867004046578901",
      deviceName: "Crane C-3",
      mcType: "JM-VL03",
      groupId: "grp_02",
      status: "offline",
      battery: 3,
      rfidTag: "RFID-B003",
      lat: 25.7700,
      lng: -80.3100,
      speed: 0,
      gpsTime: "2025-04-19 18:30:00",
      positionType: 1,
      address: "Airport Expressway, Miami, FL"
    },
    {
      imei: "867004046589012",
      deviceName: "Container Box-1",
      mcType: "AT4",
      groupId: "grp_03",
      status: "online",
      battery: 91,
      rfidTag: "RFID-C001",
      lat: 25.7740,
      lng: -80.1860,
      speed: 0,
      gpsTime: "2025-04-20 14:28:00",
      positionType: 5,
      address: "Port of Miami, FL"
    },
    {
      imei: "867004046590123",
      deviceName: "Container Box-2",
      mcType: "AT4",
      groupId: "grp_03",
      status: "idle",
      battery: 45,
      rfidTag: "RFID-C002",
      lat: 25.7760,
      lng: -80.1840,
      speed: 0,
      gpsTime: "2025-04-20 11:10:00",
      positionType: 5,
      address: "Port of Miami Dock 4, FL"
    },
    {
      imei: "867004046601234",
      deviceName: "Worker Tag P-1",
      mcType: "AT6",
      groupId: "grp_04",
      status: "online",
      battery: 82,
      rfidTag: "RFID-D001",
      lat: 25.7955,
      lng: -80.2795,
      speed: 2,
      gpsTime: "2025-04-20 14:33:00",
      positionType: 5,
      address: "Construction Site, Doral, FL"
    },
    {
      imei: "867004046612345",
      deviceName: "Worker Tag P-2",
      mcType: "AT6",
      groupId: "grp_04",
      status: "online",
      battery: 70,
      rfidTag: "RFID-D002",
      lat: 25.7965,
      lng: -80.2800,
      speed: 1,
      gpsTime: "2025-04-20 14:33:00",
      positionType: 5,
      address: "Construction Site, Doral, FL"
    }
  ],

  // ── History track for "Truck Alpha-1" ─────────────────────
  // 6 sequential positions
  trackHistory: {
    "867004046512345": [
      {
        seq: 1,
        lat: 25.7400,
        lng: -80.2600,
        gpsTime: "2025-04-20 08:02:14",
        speed: 0,
        posType: 1,
        address: "Warehouse Depot, SW 137th Ave, Miami",
        event: "Departed Warehouse"
      },
      {
        seq: 2,
        lat: 25.7490,
        lng: -80.2390,
        gpsTime: "2025-04-20 08:41:05",
        speed: 38,
        posType: 1,
        address: "SW 8th St & SW 107th Ave, Miami",
        event: "En route — Highway"
      },
      {
        seq: 3,
        lat: 25.7560,
        lng: -80.2150,
        gpsTime: "2025-04-20 09:18:33",
        speed: 22,
        posType: 1,
        address: "Coral Gables, US-1, Miami",
        event: "Slow traffic zone"
      },
      {
        seq: 4,
        lat: 25.7610,
        lng: -80.1980,
        gpsTime: "2025-04-20 10:05:50",
        speed: 0,
        posType: 5,
        address: "Brickell Financial District, Miami",
        event: "Delivery Stop #1"
      },
      {
        seq: 5,
        lat: 25.7640,
        lng: -80.1900,
        gpsTime: "2025-04-20 11:52:17",
        speed: 18,
        posType: 1,
        address: "Downtown Miami, NE 2nd Ave",
        event: "Resumed route"
      },
      {
        seq: 6,
        lat: 25.7617,
        lng: -80.1918,
        gpsTime: "2025-04-20 14:32:10",
        speed: 42,
        posType: 5,
        address: "NW 2nd Ave, Miami — Current",
        event: "Current position"
      }
    ]
  },

  // ── Sub-accounts ──────────────────────────────────────────
  subAccounts: [
    {
      id: "usr_01",
      account: "dispatcher@pinplot.pro",
      name: "Sam Rivera",
      type: 9,
      typeName: "User",
      role: "Dispatcher",
      enabledFlag: 1,
      createdAt: "2024-11-10",
      permissions: "111100",
      devices: 8
    },
    {
      id: "usr_02",
      account: "supervisor@pinplot.pro",
      name: "Jordan Lee",
      type: 9,
      typeName: "User",
      role: "Supervisor",
      enabledFlag: 1,
      createdAt: "2024-11-15",
      permissions: "111000",
      devices: 5
    },
    {
      id: "usr_03",
      account: "viewer@pinplot.pro",
      name: "Alex Kim",
      type: 9,
      typeName: "User",
      role: "Viewer",
      enabledFlag: 1,
      createdAt: "2025-01-04",
      permissions: "100000",
      devices: 11
    },
    {
      id: "usr_04",
      account: "contractor@pinplot.pro",
      name: "Maria Santos",
      type: 8,
      typeName: "Distributor",
      role: "Field Agent",
      enabledFlag: 0,
      createdAt: "2025-02-20",
      permissions: "110000",
      devices: 3
    }
  ],

  // ── Alerts / recent events ────────────────────────────────
  alerts: [
    { id: "a1", type: "low_battery",  asset: "Pickup Delta-4", msg: "Battery critical (12%)", time: "14:25", read: false },
    { id: "a2", type: "geofence_exit",asset: "Truck Alpha-1",  msg: "Left geofence: Depot Zone", time: "08:05", read: false },
    { id: "a3", type: "offline",      asset: "Crane C-3",      msg: "Device offline >8h",  time: "Yesterday", read: true  },
    { id: "a4", type: "geofence_enter",asset:"Container Box-1",msg: "Entered: Port Zone A",  time: "12:28", read: true  }
  ]
};

window.DEMO = DEMO;
