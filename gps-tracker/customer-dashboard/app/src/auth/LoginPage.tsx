import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Alert, Anchor, Button, Checkbox, Paper, PasswordInput, PinInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconAlertCircle } from '@tabler/icons-react';
import { api } from '../api/client';
import { useBranding, usePlatformName } from '../api/hooks';
import { useT } from '../i18n';
import { saveSession, type Access, type PortalUser, type UserGroup } from './session';
import classes from './LoginPage.module.css';

type Mode = 'login' | 'forgot' | 'reset';

const REMEMBER_KEY = 'portal_remembered_email';

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: branding } = useBranding();
  const platformName = usePlatformName();
  const t = useT();
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState(() => { try { return localStorage.getItem(REMEMBER_KEY) || ''; } catch { return ''; } });
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(!!email);
  const [pin, setPin] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const login = () => run(async () => {
    const data = await api<{ access_token: string; portal_user: PortalUser; usergroup: UserGroup; effective_features: string[] | null; access: Access | null }>(
      '/api/portal/login', { method: 'POST', json: { email: email.trim(), password } });
    try { remember ? localStorage.setItem(REMEMBER_KEY, email.trim()) : localStorage.removeItem(REMEMBER_KEY); } catch { /* ignore */ }
    saveSession(data.access_token, data.portal_user, data.usergroup, data.effective_features, data.access);
    queryClient.invalidateQueries();
    navigate('/dashboard', { replace: true });
  });

  const forgot = () => run(async () => {
    await api('/api/portal/auth/forgot-password', { method: 'POST', json: { email: email.trim() } });
    setInfo(t('app.login.code_sent', 'If that email has an account, a 6-digit code is on its way.'));
    setMode('reset');
  });

  const reset = () => run(async () => {
    await api('/api/portal/auth/reset-password', { method: 'POST', json: { email: email.trim(), pin, new_password: newPassword } });
    setInfo(t('app.login.password_changed', 'Password changed — sign in with your new password.'));
    setPassword('');
    setMode('login');
  });

  return (
    <div className={classes.page}>
      <div className={classes.brandSide}>
        <Text className={classes.brandName}>{platformName}</Text>
        <Text className={classes.tagline}>{branding?.tagline ?? t('app.login.tagline', 'Live vehicle tracking, trips and reporting.')}</Text>
      </div>
      <Paper className={classes.card} p="xl" shadow="xl">
        <form onSubmit={(e) => { e.preventDefault(); mode === 'login' ? login() : mode === 'forgot' ? forgot() : reset(); }}>
          <Stack gap="md">
            <div>
              <Title order={2}>{mode === 'login' ? t('app.login.sign_in', 'Sign in') : mode === 'forgot' ? t('app.login.reset_password', 'Reset password') : t('app.login.enter_code', 'Enter your code')}</Title>
              <Text c="dimmed" size="sm" mt={4}>
                {mode === 'login' ? t('app.login.welcome', 'Welcome back. Sign in to your fleet.') : mode === 'forgot'
                  ? t('app.login.we_will_email', 'We’ll email you a 6-digit code.') : t('app.login.code_sent_to', 'We sent a code to {email}.', { email })}
              </Text>
            </div>
            {error && <Alert color="red" icon={<IconAlertCircle size={18} />}>{error}</Alert>}
            {info && !error && <Alert color="brand">{info}</Alert>}
            {mode !== 'reset' && (
              <TextInput label={t('app.login.email', 'Email')} type="email" autoComplete="username" required value={email}
                         onChange={(e) => setEmail(e.currentTarget.value)} />
            )}
            {mode === 'login' && (
              <>
                <PasswordInput label={t('app.login.password', 'Password')} autoComplete="current-password" required value={password}
                               onChange={(e) => setPassword(e.currentTarget.value)} />
                <Checkbox label={t('app.login.remember_email', 'Remember my email')} checked={remember} onChange={(e) => setRemember(e.currentTarget.checked)} />
              </>
            )}
            {mode === 'reset' && (
              <>
                <PinInput length={6} type="number" value={pin} onChange={setPin} oneTimeCode />
                <PasswordInput label={t('app.login.new_password', 'New password')} description={t('app.login.at_least_8', 'At least 8 characters')} autoComplete="new-password"
                               required minLength={8} value={newPassword} onChange={(e) => setNewPassword(e.currentTarget.value)} />
              </>
            )}
            <Button type="submit" size="md" loading={busy} fullWidth>
              {mode === 'login' ? t('app.login.sign_in', 'Sign in') : mode === 'forgot' ? t('app.login.send_code', 'Send code') : t('app.login.change_password', 'Change password')}
            </Button>
            <Anchor component="button" type="button" size="sm" ta="center"
                    onClick={() => { setError(null); setInfo(null); setMode(mode === 'login' ? 'forgot' : 'login'); }}>
              {mode === 'login' ? t('app.login.forgot', 'Forgot your password?') : t('app.login.back', 'Back to sign in')}
            </Anchor>
          </Stack>
        </form>
      </Paper>
    </div>
  );
}
