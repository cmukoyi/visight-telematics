import { useEffect } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { setUnauthorizedHandler } from './api/client';
import { getSession } from './auth/session';
import { LoginPage } from './auth/LoginPage';
import { useCanOpen, useMe } from './api/hooks';
import { AppLayout, NAV } from './layout/AppLayout';
import { DashboardPage } from './pages/DashboardPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { AccountPage, ConfigurationPage } from './pages/ConfigurationPage';
import { ReportsSection } from './pages/analytics/ReportsHub';
import { InboxPage } from './pages/InboxPage';
import { MaintenanceSection } from './pages/maintenance/MaintenanceSection';

function RequireAuth({ children }: { children: JSX.Element }) {
  return getSession().token ? children : <Navigate to="/login" replace />;
}

/** Send users to the first section they can open when they open one they can't. */
function Allowed({ to, children }: { to: string; children: JSX.Element }) {
  const canOpen = useCanOpen();
  const me = useMe();
  if (canOpen(NAV.find((n) => n.to === to)!)) return children;
  // Signed in before roles existed: wait for /me rather than redirecting on missing permissions
  if (!getSession().access && me.isLoading) return null;
  const first = NAV.find(canOpen);
  return <Navigate to={first?.to ?? '/account'} replace />;
}

export function App() {
  const navigate = useNavigate();
  useEffect(() => { setUnauthorizedHandler(() => navigate('/login', { replace: true })); }, [navigate]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route path="/dashboard" element={<Allowed to="/dashboard"><DashboardPage /></Allowed>} />
        <Route path="/workspace" element={<Allowed to="/workspace"><WorkspacePage /></Allowed>} />
        <Route path="/configuration/*" element={<Allowed to="/configuration"><ConfigurationPage /></Allowed>} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/reports/*" element={<Allowed to="/reports"><ReportsSection /></Allowed>} />
        <Route path="/maintenance/*" element={<Allowed to="/maintenance"><MaintenanceSection /></Allowed>} />
        <Route path="/inbox" element={<Allowed to="/inbox"><InboxPage /></Allowed>} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
