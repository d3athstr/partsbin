import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import TOTPVerify from './TOTPVerify';

const LoginForm = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [tempToken, setTempToken] = useState('');
  const [showTOTP, setShowTOTP] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [passkeyLoading, setPasskeyLoading] = useState(false);

  const { login, loginWithPasskey, isPasskeySupported } = useAuth();
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const result = await login(username, password);

      if (result.totp_required) {
        setShowTOTP(true);
        setTempToken(result.temp_token);
      } else {
        navigate('/');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handlePasskeyLogin = async () => {
    setError('');
    setPasskeyLoading(true);

    try {
      await loginWithPasskey(username || '');
      navigate('/');
    } catch (err) {
      if (err.message.includes('cancelled') || err.name === 'NotAllowedError') {
        setError('Passkey authentication was cancelled');
      } else {
        setError(err.message || 'Passkey authentication failed');
      }
    } finally {
      setPasskeyLoading(false);
    }
  };

  if (showTOTP) {
    return (
      <TOTPVerify
        tempToken={tempToken}
        onSuccess={() => navigate('/')}
        onCancel={() => {
          setShowTOTP(false);
          setTempToken('');
        }}
      />
    );
  }

  return (
    <div className="card max-w-md mx-auto">
      <h2 className="text-2xl font-bold mb-6 text-center">Login to PartsBin</h2>

      {error && <div className="alert-error mb-4">{error}</div>}

      <form onSubmit={handleLogin}>
        <div className="mb-4">
          <label htmlFor="username" className="block text-sm font-medium mb-2">
            Username
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="input"
            placeholder="Enter your username"
            required
            autoFocus
          />
        </div>

        <div className="mb-6">
          <label htmlFor="password" className="block text-sm font-medium mb-2">
            Password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
            placeholder="Enter your password"
            required
          />
        </div>

        <button
          type="submit"
          disabled={loading || passkeyLoading}
          className="btn-primary w-full"
        >
          {loading ? 'Logging in...' : 'Login'}
        </button>
      </form>

      {/* Passkey login option */}
      {isPasskeySupported && (
        <>
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-dark-border"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-dark-surface text-dark-textMuted">or</span>
            </div>
          </div>

          <button
            type="button"
            onClick={handlePasskeyLogin}
            disabled={loading || passkeyLoading}
            className="btn-secondary w-full flex items-center justify-center gap-2"
          >
            {passkeyLoading ? (
              'Waiting for passkey...'
            ) : (
              <>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
                  />
                </svg>
                Sign in with Passkey
              </>
            )}
          </button>
        </>
      )}

      <div className="mt-4 text-center text-sm text-dark-textMuted">
        Don't have an account?{' '}
        <button type="button" onClick={() => navigate('/register')} className="link">
          Register
        </button>
      </div>
    </div>
  );
};

export default LoginForm;
