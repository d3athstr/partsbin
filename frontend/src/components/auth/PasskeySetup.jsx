import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import authService from '../../services/authService';

const PasskeySetup = ({ onComplete, onCancel }) => {
  const [passkeyName, setPasskeyName] = useState('');
  const [error, setError] = useState('');
  const queryClient = useQueryClient();

  const isSupported = authService.isPasskeySupported();

  const { data: passkeysData } = useQuery({
    queryKey: ['passkeys'],
    queryFn: () => authService.listPasskeys(),
  });

  const passkeys = passkeysData?.passkeys || [];

  const registerMutation = useMutation({
    mutationFn: (name) => authService.registerPasskey(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['passkeys'] });
      setPasskeyName('');
      setError('');
      if (onComplete) onComplete();
    },
    onError: (err) => {
      if (err.name === 'NotAllowedError') {
        setError('Passkey registration was cancelled or timed out');
      } else {
        setError(err.response?.data?.error || err.message || 'Failed to register passkey');
      }
    },
  });

  const handleRegister = (e) => {
    e.preventDefault();
    setError('');
    const name = passkeyName.trim() || `Passkey ${passkeys.length + 1}`;
    registerMutation.mutate(name);
  };

  if (!isSupported) {
    return (
      <div className="card max-w-md mx-auto">
        <h3 className="text-xl font-semibold mb-2">Passkeys Not Supported</h3>
        <p className="text-dark-textMuted mb-4">
          Your browser doesn't support passkeys. Please use a modern browser like
          Chrome, Safari, or Edge.
        </p>
        {onCancel && (
          <button onClick={onCancel} className="btn-secondary w-full">
            Close
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="card max-w-md mx-auto">
      <h3 className="text-2xl font-semibold mb-2">Passkey Authentication</h3>
      <p className="text-dark-textMuted mb-6">
        Passkeys let you sign in quickly and securely using your device's built-in
        security, like fingerprint, face recognition, or PIN.
      </p>

      {error && <div className="alert-error mb-4">{error}</div>}

      <form onSubmit={handleRegister}>
        <h4 className="font-semibold mb-3">
          {passkeys.length > 0 ? 'Add Another Passkey' : 'Set Up Your First Passkey'}
        </h4>

        <div className="mb-4">
          <label htmlFor="passkeyName" className="block text-sm font-medium mb-2">
            Passkey Name (optional)
          </label>
          <input
            id="passkeyName"
            type="text"
            value={passkeyName}
            onChange={(e) => setPasskeyName(e.target.value)}
            placeholder={`Passkey ${passkeys.length + 1}`}
            className="input"
          />
          <p className="text-xs text-dark-textMuted mt-1">
            Give your passkey a name so you can identify it later
          </p>
        </div>

        <button
          type="submit"
          disabled={registerMutation.isPending}
          className="btn-primary w-full"
        >
          {registerMutation.isPending ? 'Waiting for device...' : 'Register Passkey'}
        </button>

        {onCancel && (
          <button type="button" onClick={onCancel} className="btn-secondary w-full mt-3">
            Done
          </button>
        )}
      </form>
    </div>
  );
};

export default PasskeySetup;
