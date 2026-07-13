import { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';

const TOTPVerify = ({ tempToken, onSuccess, onCancel }) => {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { verifyTOTP } = useAuth();

  // Auto-submit when 6 digits entered
  useEffect(() => {
    if (code.length === 6) {
      handleVerify();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const handleVerify = async () => {
    if (code.length !== 6) return;

    setError('');
    setLoading(true);

    try {
      await verifyTOTP(tempToken, code);
      if (onSuccess) {
        onSuccess();
      }
    } catch (err) {
      setError(err.message || 'Invalid code');
      setCode('');
    } finally {
      setLoading(false);
    }
  };

  const handleCodeChange = (e) => {
    const value = e.target.value.replace(/\D/g, '').slice(0, 6);
    setCode(value);
  };

  return (
    <div className="card max-w-md mx-auto">
      <div className="flex items-center justify-center mb-6">
        <div className="w-16 h-16 rounded-full bg-dark-accent bg-opacity-20 flex items-center justify-center">
          <svg className="w-8 h-8 text-dark-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
            />
          </svg>
        </div>
      </div>

      <h2 className="text-2xl font-bold mb-2 text-center">Two-Factor Authentication</h2>
      <p className="text-dark-textMuted text-center mb-6">
        Enter the 6-digit code from your authenticator app
      </p>

      {error && <div className="alert-error mb-4">{error}</div>}

      <div className="mb-6">
        <input
          type="text"
          value={code}
          onChange={handleCodeChange}
          placeholder="000000"
          className="input text-center text-3xl tracking-[0.5em] font-mono"
          maxLength={6}
          autoFocus
          disabled={loading}
        />
      </div>

      <button
        onClick={handleVerify}
        disabled={loading || code.length !== 6}
        className="btn-primary w-full"
      >
        {loading ? 'Verifying...' : 'Verify'}
      </button>

      {onCancel && (
        <button onClick={onCancel} className="btn-secondary w-full mt-3">
          Cancel
        </button>
      )}

      <p className="text-xs text-dark-textMuted text-center mt-6">
        Lost access to your authenticator? Contact an administrator.
      </p>
    </div>
  );
};

export default TOTPVerify;
