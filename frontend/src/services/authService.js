import api from './api';

/**
 * Helper to convert ArrayBuffer to base64url string
 */
const bufferToBase64url = (buffer) => {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');
};

/**
 * Helper to convert base64url string to ArrayBuffer
 */
const base64urlToBuffer = (base64url) => {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(base64 + padding);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
};

/**
 * Authentication service — identical contract to GarmentGallery2.
 */
const authService = {
  register: async (username, email, password, invitationCode) => {
    const response = await api.post('/auth/register', {
      username,
      email,
      password,
      invite_code: invitationCode,
      // GG compat: some backends read invitation_code
      invitation_code: invitationCode,
    });
    return response.data;
  },

  login: async (username, password) => {
    const response = await api.post('/auth/login', { username, password });
    return response.data;
  },

  logout: async () => {
    const response = await api.post('/auth/logout');
    return response.data;
  },

  getCurrentUser: async () => {
    const response = await api.get('/auth/me');
    return response.data;
  },

  changePassword: async (currentPassword, newPassword) => {
    const response = await api.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    });
    return response.data;
  },

  // ==================== TOTP ====================

  verifyTOTP: async (tempToken, code) => {
    const response = await api.post('/auth/verify-totp', {
      temp_token: tempToken,
      code,
    });
    return response.data;
  },

  setupTOTP: async () => {
    const response = await api.get('/auth/setup-totp');
    return response.data;
  },

  enableTOTP: async (code) => {
    const response = await api.post('/auth/enable-totp', { code });
    return response.data;
  },

  disableTOTP: async (password) => {
    const response = await api.post('/auth/disable-totp', { password });
    return response.data;
  },

  // ==================== Passkeys ====================

  isPasskeySupported: () => {
    return !!(
      window.PublicKeyCredential &&
      typeof window.PublicKeyCredential === 'function'
    );
  },

  getPasskeyRegistrationOptions: async () => {
    const response = await api.get('/auth/passkey/register/options');
    return response.data;
  },

  registerPasskey: async (name = 'My Passkey') => {
    const options = await authService.getPasskeyRegistrationOptions();

    const publicKeyOptions = {
      ...options,
      challenge: base64urlToBuffer(options.challenge),
      user: {
        ...options.user,
        id: base64urlToBuffer(options.user.id),
      },
      excludeCredentials: (options.excludeCredentials || []).map((cred) => ({
        ...cred,
        id: base64urlToBuffer(cred.id),
      })),
    };

    const credential = await navigator.credentials.create({
      publicKey: publicKeyOptions,
    });

    const credentialData = {
      id: credential.id,
      rawId: bufferToBase64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        attestationObject: bufferToBase64url(credential.response.attestationObject),
      },
    };

    if (credential.response.getTransports) {
      credentialData.response.transports = credential.response.getTransports();
    }

    const response = await api.post('/auth/passkey/register/verify', {
      name,
      credential: credentialData,
    });

    return response.data;
  },

  getPasskeyAuthOptions: async (username = '') => {
    const response = await api.post('/auth/passkey/auth/options', { username });
    return response.data;
  },

  authenticateWithPasskey: async (username = '') => {
    const options = await authService.getPasskeyAuthOptions(username);

    const publicKeyOptions = {
      ...options,
      challenge: base64urlToBuffer(options.challenge),
      allowCredentials: (options.allowCredentials || []).map((cred) => ({
        ...cred,
        id: base64urlToBuffer(cred.id),
      })),
    };

    const credential = await navigator.credentials.get({
      publicKey: publicKeyOptions,
    });

    const credentialData = {
      id: credential.id,
      rawId: bufferToBase64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        authenticatorData: bufferToBase64url(credential.response.authenticatorData),
        signature: bufferToBase64url(credential.response.signature),
        userHandle: credential.response.userHandle
          ? bufferToBase64url(credential.response.userHandle)
          : null,
      },
    };

    const response = await api.post('/auth/passkey/auth/verify', {
      credential: credentialData,
    });

    return response.data;
  },

  listPasskeys: async () => {
    const response = await api.get('/auth/passkeys');
    return response.data;
  },

  deletePasskey: async (passkeyId) => {
    const response = await api.delete(`/auth/passkeys/${passkeyId}`);
    return response.data;
  },

  renamePasskey: async (passkeyId, name) => {
    const response = await api.put(`/auth/passkeys/${passkeyId}`, { name });
    return response.data;
  },
};

export default authService;
