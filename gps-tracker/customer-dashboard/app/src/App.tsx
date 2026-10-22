import { useEffect } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { setUnauthorizedHandler } from './api/client';
import { getSession } from './auth/session';
import { LoginPage } from './auth/LoginPage';
import { useCan, useMe } from './api/hooks';
import { AppLayout, NAV } from './layout/AppLayout';
import { DashboardPage } from './pages/DashboardPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { AccountPage, ConfigurationPage } from './pages/ConfigurationPage';
import { ReportsSection } from './pages/analytics/ReportsHub';
import { InboxPage } from './pages/InboxPage';

function RequireAuth({ children }: { children: JSX.Element }) {
  return getSession().token ? children : <Navigate to="/login" replace />;
}

/** Send users to the first section their role allows when they open one it doesn't. */
function Allowed({ any, children }: { any: string[]; children: JSX.Element }) {
  const can = useCan();
  const me = useMe();
  if (any.length === 0 || any.some(can)) return children;
  // Signed in before roles existed: wait for /me rather than redirecting on missing permissions
  if (!getSession().access && me.isLoading) return null;
  const first = NAV.find((n) => n.any.some(can));
  return <Navigate to={first?.to ?? '/account'} replace />;
}

const need = (to: string) => NAV.find((n) => n.to === to)!.any;

export function App() {
  const navigate = useNavigate();
  useEffect(() => { setUnauthorizedHandler(() => navigate('/login', { replace: true })); }, [navigate]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route path="/dashboard" element={<Allowed any={need('/dashboard')}><DashboardPage /></Allowed>} />
        <Route path="/workspace" element={<Allowed any={need('/workspace')}><WorkspacePage /></Allowed>} />
        <Route path="/configuration/*" element={<Allowed any={need('/configuration')}><ConfigurationPage /></Allowed>} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/reports/*" element={<Allowed any={need('/reports')}><ReportsSection /></Allowed>} />
        <Route path="/inbox" element={<Allowed any={need('/inbox')}><InboxPage /></Allowed>} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
