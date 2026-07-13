import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

const RegisterForm = () => {
  const [invitationCode, setInvitationCode] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [registered, setRegistered] = useState(false);

  const { register } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!invitationCode.trim()) {
      setError('Invitation code is required');
      return;
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);

    try {
      await register(username, email, password, invitationCode.trim());
      setRegistered(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (registered) {
    return (
      <div className="card max-w-md mx-auto text-center">
        <h2 className="text-2xl font-bold mb-4">Registration Complete</h2>
        <p className="text-dark-textMuted mb-6">
          Your account has been created. You can now log in.
        </p>
        <button onClick={() => navigate('/login')} className="btn-primary w-full">
          Go to Login
        </button>
      </div>
    );
  }

  return (
    <div className="card max-w-md mx-auto">
      <h2 className="text-2xl font-bold mb-2 text-center">Create Account</h2>
      <p className="text-dark-textMuted text-center text-sm mb-6">
        Registration requires an invitation code.
      </p>

      {error && <div className="alert-error mb-4">{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="mb-4">
          <label htmlFor="inviteCode" className="block text-sm font-medium mb-2">
            Invitation Code
          </label>
          <input
            id="inviteCode"
            type="text"
            value={invitationCode}
            onChange={(e) => setInvitationCode(e.target.value)}
            className="input font-mono"
            placeholder="Enter your invitation code"
            required
            autoFocus
          />
        </div>

        <div className="mb-4">
          <label htmlFor="reg-username" className="block text-sm font-medium mb-2">
            Username
          </label>
          <input
            id="reg-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="input"
            placeholder="Choose a username"
            required
          />
        </div>

        <div className="mb-4">
          <label htmlFor="reg-email" className="block text-sm font-medium mb-2">
            Email
          </label>
          <input
            id="reg-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input"
            placeholder="you@example.com"
            required
          />
        </div>

        <div className="mb-4">
          <label htmlFor="reg-password" className="block text-sm font-medium mb-2">
            Password
          </label>
          <input
            id="reg-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
            placeholder="At least 8 characters"
            required
          />
        </div>

        <div className="mb-6">
          <label htmlFor="reg-confirm" className="block text-sm font-medium mb-2">
            Confirm Password
          </label>
          <input
            id="reg-confirm"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="input"
            placeholder="Re-enter your password"
            required
          />
        </div>

        <button type="submit" disabled={loading} className="btn-primary w-full">
          {loading ? 'Creating account...' : 'Register'}
        </button>
      </form>

      <div className="mt-4 text-center text-sm text-dark-textMuted">
        Already have an account?{' '}
        <button type="button" onClick={() => navigate('/login')} className="link">
          Login
        </button>
      </div>
    </div>
  );
};

export default RegisterForm;
