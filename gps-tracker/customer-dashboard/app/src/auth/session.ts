// Same localStorage keys as the classic dashboard, so a login is shared between the two.
const TOKEN_KEY = 'pp_portal_token';
const USER_KEY = 'pp_portal_user';
const GROUP_KEY = 'pp_portal_group';
const FEATURES_KEY = 'pp_portal_features';
const ACCESS_KEY = 'vt_portal_access';

export interface PortalUser {
  id: string;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
  role: string;
  is_group_admin?: boolean;
}
export interface UserGroup {
  id: string;
  name: string;
}
/** The user's role, permissions and security group (from login and /me). */
export interface Access {
  role_id: string | null;
  role_name: string | null;
  role_names?: string[];
  permissions: string[];
  is_admin: boolean;
  security_group_id: string | null;
  security_group_name: string | null;
}
export interface Session {
  token: string | null;
  user: PortalUser | null;
  group: UserGroup | null;
  features: string[] | null;
  access: Access | null;
}

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function getSession(): Session {
  let token: string | null = null;
  try { token = localStorage.getItem(TOKEN_KEY); } catch { /* storage blocked */ }
  return { token, user: read(USER_KEY), group: read(GROUP_KEY), features: read(FEATURES_KEY), access: read(ACCESS_KEY) };
}

export function saveSession(token: string, user: PortalUser, group: UserGroup | null, features: string[] | null,
                            access: Access | null) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  localStorage.setItem(GROUP_KEY, JSON.stringify(group));
  localStorage.setItem(FEATURES_KEY, JSON.stringify(features));
  saveAccess(access);
}

export function saveAccess(access: Access | null) {
  try { localStorage.setItem(ACCESS_KEY, JSON.stringify(access)); } catch { /* storage blocked */ }
}

export function clearSession() {
  for (const k of [TOKEN_KEY, USER_KEY, GROUP_KEY, FEATURES_KEY, ACCESS_KEY]) {
    try { localStorage.removeItem(k); } catch { /* storage blocked */ }
  }
}

export function isAdminLike(user: PortalUser | null): boolean {
  const access = getSession().access;
  if (access) return access.is_admin;
  return !!user && (user.is_group_admin || user.role === 'admin');
}
