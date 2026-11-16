import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from './App';
import { apiClient } from './api/client';

describe('AI Coder Web Studio & Multi-Step Registration', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('completes the 3-step Email -> OTP -> Password registration wizard', async () => {
    vi.spyOn(apiClient, 'checkHealth').mockResolvedValue(true);
    const genOtpSpy = vi.spyOn(apiClient, 'generateOtp').mockResolvedValue({
      status: 'otp_sent',
      message: 'Verification code sent to dev@example.com.',
      otp_attempts: 1,
      captcha_resends: 0,
    });
    const verifyOtpSpy = vi.spyOn(apiClient, 'verifyOtp').mockResolvedValue({
      verified: true,
      verification_token: 'verified-jwt-123',
      message: 'Email verified!',
    });
    const registerSpy = vi.spyOn(apiClient, 'register').mockResolvedValue({
      access_token: 'session-jwt-999',
      email: 'dev@example.com',
      user_id: 'user-1',
    });

    vi.spyOn(apiClient, 'getDaemonStatus').mockResolvedValue({ connected: true, cwd: '/workspace' });
    vi.spyOn(apiClient, 'listServerWorkspaces').mockResolvedValue(['/workspace']);
    vi.spyOn(apiClient, 'listWorkspaceFiles').mockResolvedValue(['README.md']);
    vi.spyOn(apiClient, 'listSessions').mockResolvedValue([
      { id: 'sess-1', title: 'New session', workspace_path: '/workspace' },
    ]);
    vi.spyOn(apiClient, 'getSessionDetail').mockResolvedValue({ id: 'sess-1', messages: [] });

    render(<App />);

    // Switch from Login to Register
    fireEvent.click(screen.getByRole('button', { name: /register/i }));
    expect(screen.getByText(/verify your email/i)).toBeInTheDocument();

    // Step 1: Enter email and request OTP
    fireEvent.change(screen.getByPlaceholderText(/developer@example.com/i), {
      target: { value: 'dev@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send verification otp/i }));

    await waitFor(() => expect(genOtpSpy).toHaveBeenCalledWith('dev@example.com', false));
    expect(await screen.findByText(/enter verification code/i)).toBeInTheDocument();

    // Step 2: Enter 6-digit OTP
    fireEvent.change(screen.getByPlaceholderText('123456'), {
      target: { value: '654321' },
    });
    fireEvent.click(screen.getByRole('button', { name: /verify otp & continue/i }));

    await waitFor(() => expect(verifyOtpSpy).toHaveBeenCalledWith('dev@example.com', '654321'));
    expect(await screen.findByText(/set account password/i)).toBeInTheDocument();

    // Step 3: Set password and complete registration
    fireEvent.change(screen.getByPlaceholderText(/at least 6 characters/i), {
      target: { value: 'Secret123' },
    });
    fireEvent.change(screen.getByPlaceholderText(/re-enter password/i), {
      target: { value: 'Secret123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /create account & launch studio/i }));

    await waitFor(() =>
      expect(registerSpy).toHaveBeenCalledWith('dev@example.com', 'Secret123', 'verified-jwt-123')
    );

    // Studio UI is now mounted
    expect(await screen.findByText(/what would you like to build\?/i)).toBeInTheDocument();
  });

  it('displays SVG CAPTCHA when generateOtp returns captcha_required', async () => {
    vi.spyOn(apiClient, 'checkHealth').mockResolvedValue(true);
    vi.spyOn(apiClient, 'generateOtp').mockResolvedValue({
      status: 'captcha_required',
      message: 'Please complete the CAPTCHA challenge.',
      otp_attempts: 4,
      captcha_resends: 0,
      captcha_id: 'cap-1',
      captcha_svg: '<svg data-testid="captcha-svg"><text>AB12C</text></svg>',
    });

    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /register/i }));
    fireEvent.change(screen.getByPlaceholderText(/developer@example.com/i), {
      target: { value: 'dev@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send verification otp/i }));

    expect(await screen.findByText(/security verification required/i)).toBeInTheDocument();
    expect(screen.getByTestId('captcha-svg')).toBeInTheDocument();
  });
});