import { useState, useEffect } from 'react';
import { apiClient } from '../api/client';

export default function AuthModal({ onSuccess }) {
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  // Registration sub-steps: 'email' -> 'otp' -> 'password'
  const [regStep, setRegStep] = useState('email');

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  // OTP & CAPTCHA state
  const [otp, setOtp] = useState('');
  const [verificationToken, setVerificationToken] = useState('');
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [captchaId, setCaptchaId] = useState('');
  const [captchaSvg, setCaptchaSvg] = useState('');
  const [captchaAnswer, setCaptchaAnswer] = useState('');
  const [captchaResends, setCaptchaResends] = useState(0);

  const [infoMessage, setInfoMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [serverOnline, setServerOnline] = useState(null);

  useEffect(() => {
    let active = true;
    apiClient
      .checkHealth()
      .then((ok) => {
        if (active) setServerOnline(ok);
      })
      .catch(() => {
        if (active) setServerOnline(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const resetRegisterFlow = () => {
    setRegStep('email');
    setOtp('');
    setPassword('');
    setConfirmPassword('');
    setVerificationToken('');
    setCaptchaRequired(false);
    setCaptchaId('');
    setCaptchaSvg('');
    setCaptchaAnswer('');
    setCaptchaResends(0);
    setInfoMessage('');
    setError('');
  };

  // Login submit
  const handleLoginSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = await apiClient.login(email.trim(), password);
      onSuccess(data);
    } catch (err) {
      setError(err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  // Step 1 & Resend OTP handler
  const handleGenerateOtp = async (e, isCaptchaResend = false) => {
    if (e) e.preventDefault();
    setError('');
    setInfoMessage('');
    setLoading(true);

    try {
      const res = await apiClient.generateOtp(email.trim(), isCaptchaResend);
      setCaptchaResends(res.captcha_resends || 0);

      if (res.status === 'captcha_required') {
        setCaptchaRequired(true);
        setCaptchaId(res.captcha_id || '');
        setCaptchaSvg(res.captcha_svg || '');
        setCaptchaAnswer('');
        setRegStep('otp');
        setInfoMessage(res.message || 'Complete CAPTCHA to send OTP.');
      } else {
        setCaptchaRequired(false);
        setCaptchaId('');
        setCaptchaSvg('');
        setCaptchaAnswer('');
        setRegStep('otp');
        setInfoMessage(res.message || 'OTP sent to your email.');
      }
    } catch (err) {
      setError(err.message || 'Failed to send verification code');
    } finally {
      setLoading(false);
    }
  };

  // Verify CAPTCHA handler -> automatically sends OTP on backend
  const handleVerifyCaptcha = async (e) => {
    e.preventDefault();
    if (!captchaAnswer.trim()) return;
    setError('');
    setInfoMessage('');
    setLoading(true);

    try {
      const res = await apiClient.verifyCaptcha(
        email.trim(),
        captchaId,
        captchaAnswer.trim()
      );
      setCaptchaRequired(false);
      setCaptchaId('');
      setCaptchaSvg('');
      setCaptchaAnswer('');
      setInfoMessage(res.message || 'CAPTCHA verified! OTP sent to email.');
    } catch (err) {
      setError(err.message || 'CAPTCHA verification failed');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Verify OTP handler -> unlocks Step 3 (Password)
  const handleVerifyOtp = async (e) => {
    e.preventDefault();
    if (!otp.trim()) return;
    setError('');
    setInfoMessage('');
    setLoading(true);

    try {
      const res = await apiClient.verifyOtp(email.trim(), otp.trim());
      if (res.verified && res.verification_token) {
        setVerificationToken(res.verification_token);
        setRegStep('password');
        setInfoMessage(res.message || 'Email verified! Set your password.');
      }
    } catch (err) {
      setError(err.message || 'OTP verification failed');
    } finally {
      setLoading(false);
    }
  };

  // Step 3: Final registration with verified token + password
  const handleCompleteRegister = async (e) => {
    e.preventDefault();
    setError('');
    if (password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    try {
      const data = await apiClient.register(
        email.trim(),
        password,
        verificationToken
      );
      onSuccess(data);
    } catch (err) {
      setError(err.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-backdrop">
      <div className="auth-card">
        <div className="auth-header-row">
          <div className="brand-badge-group">
            <span className="brand-pill">AI CODER</span>
            <span className="brand-version">v0.1.0 Studio</span>
          </div>
          <span
            className={`status-indicator ${
              serverOnline ? 'status-online' : 'status-offline'
            }`}
          >
            {serverOnline === null
              ? '○ Checking...'
              : serverOnline
              ? '● Server Online'
              : '○ Server Offline'}
          </span>
        </div>

        <h1 className="auth-title">
          {mode === 'login'
            ? 'Sign in to Coding Agent'
            : regStep === 'email'
            ? 'Verify Your Email'
            : regStep === 'otp'
            ? 'Enter Verification Code'
            : 'Set Account Password'}
        </h1>
        <p className="auth-subtitle">
          {mode === 'login'
            ? 'Autonomous workspace assistant with real-time streaming & tool permissions.'
            : regStep === 'email'
            ? 'Step 1 of 3 — We will send a 6-digit OTP to confirm your email.'
            : regStep === 'otp'
            ? `Step 2 of 3 — Code sent to ${email.trim()}`
            : `Step 3 of 3 — Verified: ${email.trim()}`}
        </p>

        {error && <div className="error-banner" style={{ marginBottom: 12 }}>✖ {error}</div>}
        {infoMessage && (
          <div
            className="mono"
            style={{
              background: 'rgba(74, 222, 128, 0.1)',
              border: '1px solid rgba(74, 222, 128, 0.3)',
              color: '#86efac',
              borderRadius: 9,
              padding: '9px 12px',
              fontSize: '0.76rem',
              marginBottom: 12,
            }}
          >
            ✓ {infoMessage}
          </div>
        )}

        {/* LOGIN FORM */}
        {mode === 'login' && (
          <form onSubmit={handleLoginSubmit} className="auth-form">
            <label className="field-label">
              Email Address
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="text-input"
                placeholder="developer@example.com"
                required
              />
            </label>

            <label className="field-label">
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="text-input"
                placeholder="••••••••"
                required
              />
            </label>

            <button type="submit" disabled={loading} className="primary-btn">
              {loading ? 'Signing in...' : 'Sign In & Launch Studio'}
            </button>
          </form>
        )}

        {/* REGISTER STEP 1: EMAIL */}
        {mode === 'register' && regStep === 'email' && (
          <form onSubmit={(e) => handleGenerateOtp(e, false)} className="auth-form">
            <label className="field-label">
              Email Address
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="text-input"
                placeholder="developer@example.com"
                required
              />
            </label>

            <button type="submit" disabled={loading} className="primary-btn">
              {loading ? 'Sending OTP...' : 'Send Verification OTP'}
            </button>
          </form>
        )}

        {/* REGISTER STEP 2: OTP (+ CAPTCHA ON 4TH ATTEMPT) */}
        {mode === 'register' && regStep === 'otp' && (
          <div className="auth-form">
            {captchaRequired ? (
              <form onSubmit={handleVerifyCaptcha} className="auth-form">
                <div
                  style={{
                    background: '#141413',
                    border: '1px solid #d97757',
                    borderRadius: 10,
                    padding: 12,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  <div
                    className="mono"
                    style={{ fontSize: '0.74rem', color: '#d97757', fontWeight: 600 }}
                  >
                    Security Verification Required
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 8,
                    }}
                  >
                    <div
                      dangerouslySetInnerHTML={{ __html: captchaSvg }}
                      style={{ lineHeight: 0, flexShrink: 0 }}
                    />
                    <button
                      type="button"
                      disabled={loading || captchaResends >= 5}
                      onClick={() => handleGenerateOtp(null, true)}
                      className="card-cancel-btn mono"
                      style={{
                        flex: '1 1 auto',
                        textAlign: 'center',
                        padding: '8px 10px',
                      }}
                    >
                      ↻ Resend ({5 - captchaResends} left)
                    </button>
                  </div>

                  <input
                    type="text"
                    value={captchaAnswer}
                    onChange={(e) => setCaptchaAnswer(e.target.value)}
                    className="text-input mono"
                    placeholder="Enter the 5 characters above"
                    autoComplete="off"
                    required
                  />

                  <button type="submit" disabled={loading} className="primary-btn">
                    {loading ? 'Verifying CAPTCHA...' : 'Verify CAPTCHA & Send OTP'}
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleVerifyOtp} className="auth-form">
                <label className="field-label">
                  6-Digit OTP Code
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                    className="text-input mono"
                    placeholder="123456"
                    required
                  />
                </label>

                <button
                  type="submit"
                  disabled={loading || otp.length < 6}
                  className="primary-btn"
                >
                  {loading ? 'Verifying OTP...' : 'Verify OTP & Continue'}
                </button>

                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: 4,
                  }}
                >
                  <button
                    type="button"
                    onClick={resetRegisterFlow}
                    className="link-btn"
                    style={{ fontSize: '0.76rem', color: '#9e9e9a' }}
                  >
                    ← Change email
                  </button>

                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => handleGenerateOtp(null, false)}
                    className="link-btn"
                    style={{ fontSize: '0.76rem' }}
                  >
                    Resend OTP
                  </button>
                </div>
              </form>
            )}
          </div>
        )}

        {/* REGISTER STEP 3: PASSWORD (ONLY AFTER OTP VERIFIED) */}
        {mode === 'register' && regStep === 'password' && (
          <form onSubmit={handleCompleteRegister} className="auth-form">
            <label className="field-label">
              Create Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="text-input"
                placeholder="At least 6 characters"
                minLength={6}
                required
              />
            </label>

            <label className="field-label">
              Confirm Password
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="text-input"
                placeholder="Re-enter password"
                minLength={6}
                required
              />
            </label>

            <button type="submit" disabled={loading} className="primary-btn">
              {loading ? 'Creating Account...' : 'Create Account & Launch Studio'}
            </button>
          </form>
        )}

        <div className="auth-switch">
          {mode === 'login' ? (
            <span>
              Don&apos;t have an account?{' '}
              <button
                type="button"
                onClick={() => {
                  setMode('register');
                  resetRegisterFlow();
                }}
                className="link-btn"
              >
                Register
              </button>
            </span>
          ) : (
            <span>
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => {
                  setMode('login');
                  resetRegisterFlow();
                }}
                className="link-btn"
              >
                Sign in
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}