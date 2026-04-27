/**
 * Tracksolid Pro API Integration Layer
 * Based on: https://tracksolidprodocs.jimicloud.com/integration/integration.html
 *
 * ─────────────────────────────────────────────────────────────
 * CONFIGURATION — replace with real credentials before going live
 * ─────────────────────────────────────────────────────────────
 */

const API_CONFIG = {
  /** The request URL provided by JIMI for your node region */
  BASE_URL: "https://api.tracksolidpro.com/route/rest", // ← replace with your node URL
  APP_KEY: "YOUR_APP_KEY",      // ← from JIMI
  APP_SECRET: "YOUR_APP_SECRET" // ← from JIMI
};

// ── Internal token store ──────────────────────────────────────
let _session = {
  accessToken: null,
  refreshToken: null,
  expiresAt: 0
};

// ─────────────────────────────────────────────────────────────
// Signature helper  (MD5 via SparkMD5 loaded in index.html)
// ─────────────────────────────────────────────────────────────
function _buildSign(params) {
  const sorted = Object.keys(params)
    .filter(k => k !== "sign" && params[k] !== undefined && params[k] !== "")
    .sort()
    .map(k => `${k}${params[k]}`)
    .join("");
  const raw = API_CONFIG.APP_SECRET + sorted + API_CONFIG.APP_SECRET;
  return SparkMD5.hash(raw).toUpperCase();
}

function _timestamp() {
  const d = new Date();
  const pad = n => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ` +
         `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

// ─────────────────────────────────────────────────────────────
// Core request wrapper
// ─────────────────────────────────────────────────────────────
async function _post(method, extra = {}) {
  const base = {
    method,
    timestamp: _timestamp(),
    app_key: API_CONFIG.APP_KEY,
    sign_method: "md5",
    v: "1.0",
    format: "json",
    ...extra
  };
  base.sign = _buildSign(base);

  const body = new URLSearchParams(base);
  const res = await fetch(API_CONFIG.BASE_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body
  });
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.message || `API error ${json.code}`);
  return json;
}

// ─────────────────────────────────────────────────────────────
// 1. AUTH
//    jimi.oauth.token.get / jimi.oauth.token.refresh
// ─────────────────────────────────────────────────────────────
const Auth = {
  /**
   * POST jimi.oauth.token.get
   * @param {string} userId   - account username
   * @param {string} pwdMd5   - md5(password)
   * @param {number} expiresIn - seconds (60–7200)
   */
  async login(userId, pwdMd5, expiresIn = 7200) {
    const res = await _post("jimi.oauth.token.get", {
      user_id: userId,
      user_pwd_md5: pwdMd5,
      expires_in: expiresIn
    });
    _session = {
      accessToken: res.result.accessToken,
      refreshToken: res.result.refreshToken,
      expiresAt: Date.now() + expiresIn * 1000
    };
    localStorage.setItem("jimi_session", JSON.stringify(_session));
    return _session;
  },

  /** POST jimi.oauth.token.refresh */
  async refresh() {
    const res = await _post("jimi.oauth.token.refresh", {
      access_token: _session.accessToken,
      refresh_token: _session.refreshToken
    });
    _session.accessToken = res.result.accessToken;
    _session.expiresAt = Date.now() + 7200 * 1000;
    localStorage.setItem("jimi_session", JSON.stringify(_session));
    return _session;
  },

  restore() {
    const s = localStorage.getItem("jimi_session");
    if (s) _session = JSON.parse(s);
    return !!_session.accessToken;
  },

  isValid() {
    return !!_session.accessToken && Date.now() < _session.expiresAt;
  },

  token() { return _session.accessToken; }
};

// ─────────────────────────────────────────────────────────────
// 2. DEVICE / ASSET MANAGEMENT
// ─────────────────────────────────────────────────────────────
const Devices = {
  /**
   * jimi.user.device.list — list all devices under account
   * Response fields: imei, deviceName, mcType, deviceGroupId
   */
  async list(account) {
    return _post("jimi.user.device.list", {
      access_token: Auth.token(),
      account
    });
  },

  /**
   * jimi.track.device.detail — single device detail
   */
  async detail(imei) {
    return _post("jimi.track.device.detail", {
      access_token: Auth.token(),
      imei
    });
  },

  /**
   * jimi.device.group.list — categories / groups
   * Response: group_id, group_name
   */
  async groups(account) {
    return _post("jimi.device.group.list", {
      access_token: Auth.token(),
      account
    });
  },

  /**
   * jimi.device.group.create — add category
   */
  async createGroup(account, groupName) {
    return _post("jimi.device.group.create", {
      access_token: Auth.token(),
      account,
      group_name: groupName
    });
  }
};

// ─────────────────────────────────────────────────────────────
// 3. TRACKING / LOCATION
// ─────────────────────────────────────────────────────────────
const Tracking = {
  /**
   * jimi.device.location.getTagMsg — latest location of TAG / AirTag-style device
   * positionType=5 → BEACON
   * Response: lat, lng, gpsTime, positionType, gpsNum
   */
  async tagLocation(imei) {
    return _post("jimi.device.location.getTagMsg", {
      access_token: Auth.token(),
      imei
    });
  },

  /**
   * jimi.user.device.location.list — bulk location for all devices
   */
  async bulkLocations(account) {
    return _post("jimi.user.device.location.list", {
      access_token: Auth.token(),
      account
    });
  },

  /**
   * jimi.device.location.get — location for specific IMEIs (comma-separated)
   */
  async getLocations(imeis) {
    return _post("jimi.device.location.get", {
      access_token: Auth.token(),
      imeis: Array.isArray(imeis) ? imeis.join(",") : imeis
    });
  }
};

// ─────────────────────────────────────────────────────────────
// 4. HISTORY TRACK
// ─────────────────────────────────────────────────────────────
const History = {
  /**
   * jimi.device.track.list — history positions for a device
   * Constraints: ≤7 days per query, within last 3 months
   * Response per point: lat, lng, gpsTime, posType, speed, dir
   *
   * @param {string} imei
   * @param {string} beginTime  — "yyyy-MM-dd HH:mm:ss" UTC
   * @param {string} endTime    — "yyyy-MM-dd HH:mm:ss" UTC
   */
  async track(imei, beginTime, endTime) {
    return _post("jimi.device.track.list", {
      access_token: Auth.token(),
      imei,
      begin_time: beginTime,
      end_time: endTime
    });
  },

  /**
   * jimi.device.track.mileage — mileage summary
   */
  async mileage(imei, beginTime, endTime) {
    return _post("jimi.device.track.mileage", {
      access_token: Auth.token(),
      imei,
      begin_time: beginTime,
      end_time: endTime
    });
  }
};

// ─────────────────────────────────────────────────────────────
// 5. RFID
// ─────────────────────────────────────────────────────────────
const RFID = {
  /**
   * jimi.open.device.rfid.list — RFID tag reporting info
   * @param {string} account
   * @param {string} beginTime
   * @param {string} endTime
   * @param {string[]} [imeis]
   * @param {string[]} [cardIds]
   */
  async list(account, beginTime, endTime, imeis = [], cardIds = []) {
    const params = {
      access_token: Auth.token(),
      account,
      begin_time: beginTime,
      end_time: endTime
    };
    if (imeis.length) params.imeis = imeis.join(",");
    if (cardIds.length) params.card_ids = cardIds.join(",");
    return _post("jimi.open.device.rfid.list", params);
  }
};

// ─────────────────────────────────────────────────────────────
// 6. ACCOUNT MANAGEMENT
// ─────────────────────────────────────────────────────────────
const Accounts = {
  /**
   * jimi.user.child.list — list sub-accounts
   * Response: account, name, type (8=Distributor, 9=User), enabledFlag
   */
  async list(account) {
    return _post("jimi.user.child.list", {
      access_token: Auth.token(),
      account
    });
  },

  /**
   * jimi.user.child.create — create sub-account
   * @param {Object} opts - { account, name, pwd, type, permissions }
   */
  async create(opts) {
    return _post("jimi.user.child.create", {
      access_token: Auth.token(),
      ...opts
    });
  },

  /**
   * jimi.user.child.update — edit sub-account
   */
  async update(opts) {
    return _post("jimi.user.child.update", {
      access_token: Auth.token(),
      ...opts
    });
  },

  /**
   * jimi.user.child.del — remove sub-account
   */
  async remove(account, subAccount) {
    return _post("jimi.user.child.del", {
      access_token: Auth.token(),
      account,
      sub_account: subAccount
    });
  }
};

// ─────────────────────────────────────────────────────────────
// Export (global for non-module pages)
// ─────────────────────────────────────────────────────────────
window.JimiAPI = { Auth, Devices, Tracking, History, RFID, Accounts, _session };
