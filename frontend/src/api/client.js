const RAW_ENV_API_URL = (import.meta.env.VITE_API_URL || '').trim().replace(/\/$/, '');

function normalizeApiUrl(raw) {
  if (!raw) return '';
  // If Render's `fromService -> property: host` injected just the service slug (no dot, e.g. "ai-agent-sandbox-backend-dgcj")
  if (!/^https?:\/\//i.test(raw) && !raw.includes('.')) {
    return `https://${raw}.onrender.com`;
  }
  if (!/^https?:\/\//i.test(raw)) {
    return `https://${raw}`;
  }
  return raw;
}

const ENV_API_URL = normalizeApiUrl(RAW_ENV_API_URL);

function isLocalOrCloudShell() {
  if (typeof window === 'undefined') return false;
  const host = window.location.hostname;
  return (
    host === 'localhost' ||
    host === '127.0.0.1' ||
    host.includes('.cloudshell.dev')
  );
}

export function getApiBaseUrl() {
  if (isLocalOrCloudShell()) {
    return '';
  }
  return ENV_API_URL;
}

export function getStoredAuth() {
  return {
    token: localStorage.getItem('ai_coder_token') || '',
    email: localStorage.getItem('ai_coder_email') || '',
    userId: localStorage.getItem('ai_coder_user_id') || '',
  };
}

export function setStoredAuth({ access_token, email, user_id }) {
  localStorage.setItem('ai_coder_token', access_token || '');
  localStorage.setItem('ai_coder_email', email || '');
  localStorage.setItem('ai_coder_user_id', user_id || '');
}

export function clearStoredAuth() {
  localStorage.removeItem('ai_coder_token');
  localStorage.removeItem('ai_coder_email');
  localStorage.removeItem('ai_coder_user_id');
}

async function request(path, options = {}) {
  const baseUrl = getApiBaseUrl();
  const { token } = getStoredAuth();

  const authHeaders = {};
  if (token) {
    if (isLocalOrCloudShell()) {
      authHeaders['X-Auth-Token'] = token;
    } else {
      authHeaders['Authorization'] = `Bearer ${token}`;
      authHeaders['X-Auth-Token'] = token;
    }
  }

  const headers = {
    'Content-Type': 'application/json',
    ...authHeaders,
    ...(options.headers || {}),
  };

  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let detail = `Server returned ${response.status}`;
    try {
      const errData = await response.json();
      detail = errData.detail || errData.message || detail;
    } catch {
      // ignore JSON parse failure
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export const apiClient = {
  async checkHealth() {
    const baseUrl = getApiBaseUrl();
    const res = await fetch(`${baseUrl}/api/health`);
    return res.ok;
  },

  async login(email, password) {
    return request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },

  async generateOtp(email, isCaptchaResend = false) {
    return request('/api/auth/generate-otp', {
      method: 'POST',
      body: JSON.stringify({
        email,
        is_captcha_resend: isCaptchaResend,
      }),
    });
  },

  async verifyCaptcha(email, captchaId, captchaAnswer) {
    return request('/api/auth/verify-captcha', {
      method: 'POST',
      body: JSON.stringify({
        email,
        captcha_id: captchaId,
        captcha_answer: captchaAnswer,
      }),
    });
  },

  async verifyOtp(email, otp) {
    return request('/api/auth/verify-otp', {
      method: 'POST',
      body: JSON.stringify({ email, otp }),
    });
  },

  async register(email, password, verificationToken) {
    return request('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        email,
        password,
        verification_token: verificationToken,
      }),
    });
  },

  async getDaemonStatus() {
    try {
      return await request('/api/daemon/status');
    } catch {
      return { connected: false, cwd: '' };
    }
  },

  async claimDaemonBridge(bridgeId) {
    try {
      return await request(
        `/api/daemon/claim?bridge_id=${encodeURIComponent(bridgeId)}`,
        { method: 'POST' }
      );
    } catch {
      return { connected: false, cwd: '' };
    }
  },

  async browseFolders(path = '') {
    const q = path ? `?path=${encodeURIComponent(path)}` : '';
    return request(`/api/fs/browse${q}`);
  },

  async listServerWorkspaces() {
    try {
      const data = await request('/api/workspaces');
      return data.workspaces || [];
    } catch {
      return [];
    }
  },

  async listWorkspaceFiles(workspace) {
    try {
      const data = await request(
        `/api/workspace/files?workspace=${encodeURIComponent(workspace || '')}`
      );
      return data.files || [];
    } catch {
      return [];
    }
  },

  async readWorkspaceFile(workspace, path) {
    try {
      return await request(
        `/api/workspace/file?workspace=${encodeURIComponent(
          workspace || ''
        )}&path=${encodeURIComponent(path)}`
      );
    } catch (err) {
      return { path, content: '', error: err.message };
    }
  },

  async listSessions(workspacePath) {
    const query = workspacePath
      ? `?workspace_path=${encodeURIComponent(workspacePath)}`
      : '';
    return request(`/api/sessions${query}`);
  },

  async createSession(workspacePath, title = 'Fresh CLI Session') {
    return request('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({
        title,
        workspace_path: workspacePath,
      }),
    });
  },

  async getSessionDetail(sessionId) {
    return request(`/api/sessions/${sessionId}`);
  },

  getWebSocketUrl(sessionId) {
    const baseUrl = getApiBaseUrl();
    const { token } = getStoredAuth();
    const query = `token=${encodeURIComponent(token)}&session_id=${encodeURIComponent(
      sessionId
    )}&client_type=web`;

    if (!baseUrl) {
      const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${wsProto}//${window.location.host}/api/ws/agent?${query}`;
    }
    const wsBase = baseUrl
      .replace(/^https:\/\//, 'wss://')
      .replace(/^http:\/\//, 'ws://');
    return `${wsBase}/api/ws/agent?${query}`;
  },
};