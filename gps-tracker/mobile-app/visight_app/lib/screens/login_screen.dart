import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../session.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// Sign in with the same email and password as the customer dashboard.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false, _hidePassword = true;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _signIn() async {
    if (_email.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = 'Enter your email and password.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await SessionScope.read(context).signIn(_email.text, _password.text);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final expired = SessionScope.of(context).signedOutMessage;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: AutofillGroup(
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const Center(child: BrandMark(size: 72)),
                  const SizedBox(height: 24),
                  const Text('ViSight Track',
                      textAlign: TextAlign.center, style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 6),
                  const Text('Sign in with your customer dashboard account',
                      textAlign: TextAlign.center, style: TextStyle(color: AppColors.muted)),
                  const SizedBox(height: 32),
                  if (expired != null && _error == null) _Banner(text: expired),
                  if (_error != null) _Banner(text: _error!, error: true),
                  TextField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.username, AutofillHints.email],
                    textInputAction: TextInputAction.next,
                    autocorrect: false,
                    decoration: const InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.mail_outline)),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: _password,
                    obscureText: _hidePassword,
                    autofillHints: const [AutofillHints.password],
                    textInputAction: TextInputAction.done,
                    onSubmitted: (_) => _signIn(),
                    decoration: InputDecoration(
                      labelText: 'Password',
                      prefixIcon: const Icon(Icons.lock_outline),
                      suffixIcon: IconButton(
                        icon: Icon(_hidePassword ? Icons.visibility : Icons.visibility_off),
                        onPressed: () => setState(() => _hidePassword = !_hidePassword),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: _busy ? null : _signIn,
                    child: _busy
                        ? const SizedBox(
                            width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : const Text('Sign in', style: TextStyle(fontSize: 16)),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: () => showDialog(
                        context: context, builder: (_) => _ForgotPasswordDialog(email: _email.text.trim())),
                    child: const Text('Forgot password?'),
                  ),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.text, this.error = false});
  final String text;
  final bool error;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: error ? const Color(0xFFFDECEA) : const Color(0xFFE8F0FE),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(text, style: TextStyle(color: error ? const Color(0xFFB3261E) : AppColors.navy)),
    );
  }
}

/// The dashboard's reset flow: email a 6-digit PIN, then set a new password with it.
class _ForgotPasswordDialog extends StatefulWidget {
  const _ForgotPasswordDialog({required this.email});
  final String email;

  @override
  State<_ForgotPasswordDialog> createState() => _ForgotPasswordDialogState();
}

class _ForgotPasswordDialogState extends State<_ForgotPasswordDialog> {
  late final _email = TextEditingController(text: widget.email);
  final _pin = TextEditingController();
  final _password = TextEditingController();
  bool _pinSent = false, _busy = false;
  String? _message;

  @override
  void dispose() {
    _email.dispose();
    _pin.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final api = SessionScope.read(context).api;
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      if (!_pinSent) {
        await api.post('/api/portal/auth/forgot-password', {'email': _email.text.trim()});
        setState(() => _pinSent = true);
      } else {
        await api.post('/api/portal/auth/reset-password',
            {'email': _email.text.trim(), 'pin': _pin.text.trim(), 'new_password': _password.text});
        if (!mounted) return;
        Navigator.pop(context);
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('Password changed. Sign in with your new password.')));
      }
    } on ApiException catch (e) {
      setState(() => _message = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Reset password'),
      content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(_pinSent
            ? 'If that email is registered, a 6-digit PIN is on its way. Enter it with your new password.'
            : "Enter your email and we'll send you a PIN."),
        const SizedBox(height: 16),
        TextField(
          controller: _email,
          enabled: !_pinSent,
          keyboardType: TextInputType.emailAddress,
          decoration: const InputDecoration(labelText: 'Email'),
        ),
        if (_pinSent) ...[
          const SizedBox(height: 12),
          TextField(
              controller: _pin, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'PIN')),
          const SizedBox(height: 12),
          TextField(
              controller: _password, obscureText: true, decoration: const InputDecoration(labelText: 'New password')),
        ],
        if (_message != null) ...[
          const SizedBox(height: 12),
          Text(_message!, style: const TextStyle(color: Color(0xFFB3261E))),
        ],
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        TextButton(
          onPressed: _busy ? null : _submit,
          child: Text(_pinSent ? 'Change password' : 'Send PIN'),
        ),
      ],
    );
  }
}
