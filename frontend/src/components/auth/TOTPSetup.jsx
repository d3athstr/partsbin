import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import authService from '../../services/authService';

const TOTPSetup = ({ onComplete, onCancel }) => {
  const [qrCode, setQrCode] = useState(null);
  const [secret, setSecret] = useState(null);
  const [verificationCode, setVerificationCode] = useState('');
  const [error, setError] = useState('');

  // Get TOTP setup data (QR code)
  const setupMutation = useMutation({
    mutationFn: () => authService.setupTOTP(),
    onSuccess: (data) => {
      setQrCode(data.qr_code);
      setSecret(data.secret);
    },
    onError: (err) => {
      setError(err.response?.data?.error || 'Failed to generate TOTP setup');
    },
  });

  // Enable TOTP with verification code
  const enableMutation = useMutation({
    mutationFn: (code) => authService.enableTOTP(code),
    onSuccess: () => {
      if (onComplete) onComplete();
    },
    onError: (err) => {
      setError(err.response?.data?.error || 'Invalid verification code');
    },
  });

  const handleStartSetup = () => {
    setError('');
    setupMutation.mutate();
  };

  const handleVerifyAndEnable = (e) => {
    e.preventDefault();
    setError('');

    if (!verificationCode || verificationCode.length !== 6) {
      setError('Please enter a 6-digit code');
      return;
    }

    enableMutation.mutate(verificationCode);
  };

  return (
    <div className="card max-w-md mx-auto">
      <h3 className="text-2xl font-semibold mb-4">Enable Authenticator App</h3>

      {!qrCode ? (
        <div>
          <p className="text-dark-textMuted mb-6">
            Use an authenticator app like Google Authenticator or Authy to generate
            verification codes.
          </p>

          {error && <div className="alert-error mb-4">{error}</div>}

          <button
            onClick={handleStartSetup}
            disabled={setupMutation.isPending}
            className="btn-primary w-full"
          >
            {setupMutation.isPending ? 'Setting up...' : 'Start Setup'}
          </button>

          {onCancel && (
            <button onClick={onCancel} className="btn-secondary w-full mt-3">
              Cancel
            </button>
          )}
        </div>
      ) : (
        <div>
          <div className="mb-6">
            <h4 className="font-semibold mb-3">Step 1: Scan QR Code</h4>
            <p className="text-dark-textMuted text-sm mb-4">
              Open your authenticator app and scan this QR code:
            </p>

            <div className="bg-white p-4 rounded-lg inline-block">
              <img
                src={`data:image/png;base64,${qrCode}`}
                alt="TOTP QR Code"
                className="w-48 h-48"
              />
            </div>

            <div className="mt-4 p-3 bg-dark-elevated rounded-lg">
              <p className="text-xs text-dark-textMuted mb-1">
                Can't scan? Enter this secret manually:
              </p>
              <code className="text-sm text-dark-accent font-mono break-all">{secret}</code>
            </div>
          </div>

          <form onSubmit={handleVerifyAndEnable}>
            <div className="mb-6">
              <h4 className="font-semibold mb-3">Step 2: Verify Code</h4>
              <p className="text-dark-textMuted text-sm mb-3">
                Enter the 6-digit code from your authenticator app:
              </p>

              <input
                type="text"
                value={verificationCode}
                onChange={(e) =>
                  setVerificationCode(e.target.value.replace(/\D/g, '').slice(0, 6))
                }
                placeholder="000000"
                className="input text-center text-2xl tracking-widest font-mono"
                maxLength={6}
                autoFocus
              />
            </div>

            {error && <div className="alert-error mb-4">{error}</div>}

            <button
              type="submit"
              disabled={enableMutation.isPending || verificationCode.length !== 6}
              className="btn-primary w-full"
            >
              {enableMutation.isPending ? 'Verifying...' : 'Enable Authenticator'}
            </button>

            {onCancel && (
              <button type="button" onClick={onCancel} className="btn-secondary w-full mt-3">
                Cancel
              </button>
            )}
          </form>
        </div>
      )}
    </div>
  );
};

export default TOTPSetup;
