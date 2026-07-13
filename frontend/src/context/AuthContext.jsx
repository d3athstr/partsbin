import { createContext, useContext, useState, useEffect } from 'react';
import authService from '../services/authService';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Check if user is logged in on mount
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const data = await authService.getCurrentUser();
        setUser(data.user);
      } catch (err) {
        setUser(null);
      } finally {
        setLoading(false);
      }
    };

    checkAuth();
  }, []);

  /**
   * Login with username/password.
   * Returns {totp_required, temp_token} if TOTP is enabled.
   */
  const login = async (username, password) => {
    try {
      setError(null);
      const data = await authService.login(username, password);

      if (data.totp_required) {
        return {
          totp_required: true,
          temp_token: data.temp_token,
        };
      }

      setUser(data.user);
      return { success: true };
    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Login failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  };

  /**
   * Verify TOTP code during login
   */
  const verifyTOTP = async (tempToken, code) => {
    try {
      setError(null);
      const data = await authService.verifyTOTP(tempToken, code);
      setUser(data.user);
      return { success: true };
    } catch (err) {
      const errorMessage = err.response?.data?.error || 'TOTP verification failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  };

  /**
   * Login with passkey
   */
  const loginWithPasskey = async (username = '') => {
    try {
      setError(null);
      const data = await authService.authenticateWithPasskey(username);
      setUser(data.user);
      return { success: true };
    } catch (err) {
      const errorMessage =
        err.response?.data?.error || err.message || 'Passkey authentication failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  };

  /**
   * Logout user
   */
  const logout = async () => {
    try {
      await authService.logout();
      setUser(null);
      setError(null);
    } catch (err) {
      console.error('Logout error:', err);
      setUser(null);
    }
  };

  /**
   * Register new user (requires invitation code)
   */
  const register = async (username, email, password, invitationCode) => {
    try {
      setError(null);
      const data = await authService.register(username, email, password, invitationCode);
      return data;
    } catch (err) {
      const errorMessage = err.response?.data?.error || 'Registration failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  };

  /**
   * Refresh user data
   */
  const refreshUser = async () => {
    try {
      const data = await authService.getCurrentUser();
      setUser(data.user);
    } catch (err) {
      setUser(null);
    }
  };

  const isPasskeySupported = authService.isPasskeySupported();

  const value = {
    user,
    loading,
    error,
    login,
    verifyTOTP,
    loginWithPasskey,
    logout,
    register,
    refreshUser,
    isAuthenticated: !!user,
    isAdmin: user?.is_admin || false,
    isPasskeySupported,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

/**
 * Hook to use auth context
 */
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

export default AuthContext;
