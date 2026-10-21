import { useEffect } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { setUnauthorizedHandler } from './api/client';
import { getSession } from './auth/session';
import { LoginPage } from './auth/LoginPage';
import { AppLayout } from './layout/AppLayout';
import { DashboardPage } from './pages/DashboardPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { ConfigurationPage } from './pages/ConfigurationPage';
import { ReportsPage } from './pages/ReportsPage';
import { InboxPage } from './pages/InboxPage';

function RequireAuth({ children }: { children: JSX.Element }) {
  return getSession().token ? children : <Navigate to="/login" replace />;
}

export function App() {
  const navigate = useNavigate();
  useEffect(() => { setUnauthorizedHandler(() => navigate('/login', { replace: true })); }, [navigate]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/configuration/*" element={<ConfigurationPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/inbox" element={<InboxPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
