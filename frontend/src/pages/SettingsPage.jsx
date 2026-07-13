import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import authService from '../services/authService';
import adminService from '../services/adminService';
import ingestService from '../services/ingestService';
import TOTPSetup from '../components/auth/TOTPSetup';
import PasskeySetup from '../components/auth/PasskeySetup';
import { fmtDate, fmtDateTime } from '../utils/format';

const TokenStatus = ({ status }) => {
  const s = (status || 'unknown').toLowerCase();
  if (s === 'ok' || s === 'valid') {
    return <span className="text-sm text-dark-textMuted">token OK</span>;
  }
  if (s === 'missing') return <span className="chip-warn">token missing</span>;
  return <span className="chip-alarm">token {s}</span>;
};

const SettingsPage = () => {
  const { user, isPasskeySupported, refreshUser } = useAuth();
  const queryClient = useQueryClient();

  const [showTOTPSetup, setShowTOTPSetup] = useState(false);
  const [showPasskeySetup, setShowPasskeySetup] = useState(false);
  const [disablePassword, setDisablePassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Change password form
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNew, setConfirmNew] = useState('');

  // Invitations
  const [showCreateInvite, setShowCreateInvite] = useState(false);
  const [inviteNote, setInviteNote] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [copiedCode, setCopiedCode] = useState(null);

  const flash = (msg) => {
    setSuccess(msg);
    setError('');
  };
  const flashErr = (err, fallback) => {
    setError(err.response?.data?.error || fallback);
    setSuccess('');
  };

  // ==================== Queries ====================

  const { data: passkeysData } = useQuery({
    queryKey: ['passkeys'],
    queryFn: () => authService.listPasskeys(),
  });
  const passkeys = passkeysData?.passkeys || [];

  const { data: invitationsData, isLoading: invitationsLoading } = useQuery({
    queryKey: ['adminInvitations'],
    queryFn: () => adminService.getInvitations(),
    enabled: !!user?.is_admin,
  });

  const { data: adminUsersData, isLoading: adminUsersLoading } = useQuery({
    queryKey: ['adminUsers'],
    queryFn: () => adminService.getUsers(),
    enabled: !!user?.is_admin,
  });
  const adminUsers = adminUsersData?.users || [];

  const { data: ingestData, isLoading: ingestLoading } = useQuery({
    queryKey: ['ingestStatus'],
    queryFn: () => ingestService.status(),
  });
  const ingestAccounts = Array.isArray(ingestData)
    ? ingestData
    : ingestData?.accounts || ingestData?.items || [];

  // ==================== Mutations ====================

  const changePasswordMutation = useMutation({
    mutationFn: ({ current, next }) => authService.changePassword(current, next),
    onSuccess: () => {
      flash('Password changed');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmNew('');
    },
    onError: (err) => flashErr(err, 'Failed to change password'),
  });

  const disableTOTPMutation = useMutation({
    mutationFn: (password) => authService.disableTOTP(password),
    onSuccess: () => {
      flash('Authenticator app has been disabled');
      setDisablePassword('');
      refreshUser();
    },
    onError: (err) => flashErr(err, 'Failed to disable authenticator'),
  });

  const deletePasskeyMutation = useMutation({
    mutationFn: (passkeyId) => authService.deletePasskey(passkeyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['passkeys'] });
      flash('Passkey deleted');
    },
    onError: (err) => flashErr(err, 'Failed to delete passkey'),
  });

  const renamePasskeyMutation = useMutation({
    mutationFn: ({ passkeyId, name }) => authService.renamePasskey(passkeyId, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['passkeys'] });
      flash('Passkey renamed');
    },
    onError: (err) => flashErr(err, 'Failed to rename passkey'),
  });

  const createInviteMutation = useMutation({
    mutationFn: (options) => adminService.createInvitation(options),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['adminInvitations'] });
      setShowCreateInvite(false);
      setInviteNote('');
      setInviteEmail('');
      flash(data.message || 'Invitation code created');
    },
    onError: (err) => flashErr(err, 'Failed to create invitation'),
  });

  const deleteInviteMutation = useMutation({
    mutationFn: (inviteId) => adminService.deleteInvitation(inviteId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['adminInvitations'] }),
    onError: (err) => flashErr(err, 'Failed to delete invitation'),
  });

  const userActionMutation = useMutation({
    mutationFn: ({ action, userId, account }) => {
      if (action === 'approve') return adminService.approveUser(userId);
      if (action === 'revoke') return adminService.revokeUser(userId);
      if (action === 'account') return adminService.setGmailAccount(userId, account);
      if (action === 'delete') return adminService.deleteUser(userId);
      return Promise.reject(new Error('unknown action'));
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] });
      flash(data?.message || 'User updated');
    },
    onError: (err) => flashErr(err, 'Failed to update user'),
  });

  const runIngestMutation = useMutation({
    mutationFn: () => ingestService.run(),
    onSuccess: (data) => {
      flash(data?.message || 'Ingest run triggered');
      queryClient.invalidateQueries({ queryKey: ['ingestStatus'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['reviewPending'] });
    },
    onError: (err) => flashErr(err, 'Ingest run failed'),
  });

  // ==================== Handlers ====================

  const handleChangePassword = (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }
    if (newPassword !== confirmNew) {
      setError('New passwords do not match');
      return;
    }
    changePasswordMutation.mutate({ current: currentPassword, next: newPassword });
  };

  const handleDisableTOTP = (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (!disablePassword) {
      setError('Please enter your password');
      return;
    }
    disableTOTPMutation.mutate(disablePassword);
  };

  const handleRenamePasskey = (passkey) => {
    const name = window.prompt('New passkey name:', passkey.name);
    if (name && name.trim() && name.trim() !== passkey.name) {
      renamePasskeyMutation.mutate({ passkeyId: passkey.id, name: name.trim() });
    }
  };

  const handleDeletePasskey = (passkeyId, passkeyName) => {
    if (
      window.confirm(
        `Are you sure you want to delete "${passkeyName}"? You won't be able to use it to sign in anymore.`
      )
    ) {
      deletePasskeyMutation.mutate(passkeyId);
    }
  };

  const handleCopyCode = async (code) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedCode(code);
      setTimeout(() => setCopiedCode(null), 2000);
    } catch {
      setError('Failed to copy to clipboard');
    }
  };

  const handleCreateInvite = (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    createInviteMutation.mutate({
      note: inviteNote || undefined,
      email: inviteEmail || undefined,
    });
  };

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="mb-2">Settings</h1>
      <p className="text-dark-textMuted mb-6">
        Manage your account security, invitations, and email ingestion
      </p>

      {success && <div className="alert-info mb-4">{success}</div>}
      {error && <div className="alert-error mb-4">{error}</div>}

      {/* Account */}
      <div className="card mb-6">
        <h2 className="text-xl font-semibold mb-4">Account</h2>
        <div className="grid sm:grid-cols-3 gap-4 text-sm mb-6">
          <div>
            <p className="text-dark-textMuted mb-1">Username</p>
            <p>{user?.username}</p>
          </div>
          <div>
            <p className="text-dark-textMuted mb-1">Email</p>
            <p>{user?.email}</p>
          </div>
          <div>
            <p className="text-dark-textMuted mb-1">Role</p>
            <p>{user?.is_admin ? 'Administrator' : 'User'}</p>
          </div>
        </div>

        <h3 className="text-base font-semibold mb-3">Change Password</h3>
        <form onSubmit={handleChangePassword} className="grid sm:grid-cols-3 gap-3">
          <input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            placeholder="Current password"
            className="input"
            required
            autoComplete="current-password"
          />
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="New password"
            className="input"
            required
            autoComplete="new-password"
          />
          <input
            type="password"
            value={confirmNew}
            onChange={(e) => setConfirmNew(e.target.value)}
            placeholder="Confirm new password"
            className="input"
            required
            autoComplete="new-password"
          />
          <div className="sm:col-span-3">
            <button
              type="submit"
              disabled={changePasswordMutation.isPending}
              className="btn-secondary"
            >
              {changePasswordMutation.isPending ? 'Changing...' : 'Change Password'}
            </button>
          </div>
        </form>
      </div>

      {/* Two-Factor Authentication */}
      <div className="card mb-6">
        <h2 className="text-xl font-semibold mb-4">Two-Factor Authentication</h2>

        {/* TOTP */}
        <div className="mb-6 p-4 bg-dark-elevated rounded-lg">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <h3 className="font-semibold mb-1">Authenticator App</h3>
              <p className="text-dark-textMuted text-sm">
                {user?.totp_enabled
                  ? 'Required when logging in with username and password.'
                  : 'Use Google Authenticator or Authy to generate one-time codes.'}
              </p>
            </div>
            <span className="text-sm text-dark-textMuted whitespace-nowrap">
              {user?.totp_enabled ? 'Enabled' : 'Not set up'}
            </span>
          </div>

          {!showTOTPSetup &&
            (user?.totp_enabled ? (
              <form onSubmit={handleDisableTOTP} className="flex gap-2">
                <input
                  type="password"
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                  placeholder="Enter password to disable"
                  className="input flex-1"
                />
                <button
                  type="submit"
                  disabled={disableTOTPMutation.isPending}
                  className="btn-secondary"
                >
                  {disableTOTPMutation.isPending ? 'Disabling...' : 'Disable'}
                </button>
              </form>
            ) : (
              <button onClick={() => setShowTOTPSetup(true)} className="btn-primary">
                Set Up Authenticator
              </button>
            ))}

          {showTOTPSetup && (
            <div className="mt-4">
              <TOTPSetup
                onComplete={() => {
                  setShowTOTPSetup(false);
                  flash('Authenticator app has been enabled');
                  refreshUser();
                }}
                onCancel={() => setShowTOTPSetup(false)}
              />
            </div>
          )}
        </div>

        {/* Passkeys */}
        <div className="p-4 bg-dark-elevated rounded-lg">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <h3 className="font-semibold mb-1">Passkeys</h3>
              <p className="text-dark-textMuted text-sm">
                Sign in without a password using biometrics or a security key.
              </p>
            </div>
            <span className="text-sm text-dark-textMuted whitespace-nowrap">
              {passkeys.length > 0 ? `${passkeys.length} registered` : 'Not set up'}
            </span>
          </div>

          {passkeys.length > 0 && !showPasskeySetup && (
            <div className="mb-4 space-y-2">
              {passkeys.map((passkey) => (
                <div
                  key={passkey.id}
                  className="flex items-center justify-between p-3 bg-dark-surface rounded-lg"
                >
                  <div>
                    <p className="font-medium text-sm">{passkey.name}</p>
                    <p className="text-xs text-dark-textMuted">
                      Created {fmtDate(passkey.created_at)}
                      {passkey.last_used_at && <> · Last used {fmtDate(passkey.last_used_at)}</>}
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleRenamePasskey(passkey)}
                      disabled={renamePasskeyMutation.isPending}
                      className="text-dark-textMuted hover:text-dark-text p-1"
                      title="Rename passkey"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>
                    <button
                      onClick={() => handleDeletePasskey(passkey.id, passkey.name)}
                      disabled={deletePasskeyMutation.isPending}
                      className="text-dark-textMuted hover:text-dark-error p-1"
                      title="Delete passkey"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!showPasskeySetup &&
            (isPasskeySupported ? (
              <button onClick={() => setShowPasskeySetup(true)} className="btn-primary">
                {passkeys.length > 0 ? 'Add Another Passkey' : 'Set Up Passkey'}
              </button>
            ) : (
              <p className="text-dark-warning text-sm">Your browser doesn't support passkeys.</p>
            ))}

          {showPasskeySetup && (
            <div className="mt-4">
              <PasskeySetup
                onComplete={() => {
                  setShowPasskeySetup(false);
                  flash('Passkey registered');
                  queryClient.invalidateQueries({ queryKey: ['passkeys'] });
                }}
                onCancel={() => setShowPasskeySetup(false)}
              />
            </div>
          )}
        </div>
      </div>

      {/* Gmail accounts / ingest */}
      <div className="card mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold">Gmail Accounts</h2>
            <p className="text-dark-textMuted text-sm">
              Order-email ingestion runs automatically every 30 minutes.
            </p>
          </div>
          {user?.is_admin && (
            <button
              onClick={() => runIngestMutation.mutate()}
              disabled={runIngestMutation.isPending}
              className="btn-secondary"
            >
              {runIngestMutation.isPending ? 'Running...' : 'Run Ingest Now'}
            </button>
          )}
        </div>

        {ingestLoading ? (
          <div className="flex justify-center py-6">
            <div className="w-8 h-8 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
          </div>
        ) : ingestAccounts.length === 0 ? (
          <p className="text-sm text-dark-textMuted">No Gmail accounts configured.</p>
        ) : (
          <div className="space-y-3">
            {ingestAccounts.map((acct, i) => {
              const status = (acct.token_status ?? acct.token ?? 'unknown').toLowerCase();
              const tokenBad = !(status === 'ok' || status === 'valid');
              const reauthUrl =
                acct.reauth_url ||
                (acct.user || acct.account
                  ? `/api/oauth/login/${acct.user || acct.account}`
                  : null);
              return (
                <div key={acct.email || acct.account || i} className="p-4 bg-dark-elevated rounded-lg">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium text-sm">
                      {acct.email || acct.account || acct.user}
                    </p>
                    <TokenStatus status={status} />
                  </div>
                  <div className="grid sm:grid-cols-3 gap-2 mt-2 text-xs text-dark-textMuted">
                    <p>Last poll: {fmtDateTime(acct.last_poll)}</p>
                    <p>
                      Processed:{' '}
                      {acct.processed ?? acct.processed_count ?? acct.counts?.processed ?? '—'}
                    </p>
                    <p>
                      Orders:{' '}
                      {acct.orders ?? acct.order_count ?? acct.counts?.orders ?? '—'}
                    </p>
                  </div>
                  {acct.last_error && (
                    <p className="text-xs text-dark-error mt-2 break-words">{acct.last_error}</p>
                  )}
                  {tokenBad && reauthUrl && (
                    <a
                      href={reauthUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="link text-sm inline-block mt-2"
                    >
                      Re-authorize Google access →
                    </a>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Users (Admin Only) */}
      {user?.is_admin && (
        <div className="card mb-6">
          <div className="mb-4">
            <h2 className="text-xl font-semibold">Users</h2>
            <p className="text-dark-textMuted text-sm">
              Approve registrations and map users to their order-ingest Gmail account
            </p>
          </div>
          {adminUsersLoading ? (
            <div className="flex justify-center py-6">
              <div className="w-8 h-8 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
            </div>
          ) : (
            <div className="space-y-3">
              {adminUsers.map((u) => (
                <div key={u.id} className="p-4 bg-dark-elevated rounded-lg">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-medium text-sm">
                        {u.username}
                        {u.is_admin && (
                          <span className="text-dark-textMuted font-normal"> · admin</span>
                        )}
                        {u.id === user.id && (
                          <span className="text-dark-textMuted font-normal"> · you</span>
                        )}
                      </p>
                      <p className="text-xs text-dark-textMuted">{u.email}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {!u.is_approved && <span className="chip-warn">pending approval</span>}
                      {u.id !== user.id && (
                        u.is_approved ? (
                          <button
                            onClick={() => userActionMutation.mutate({ action: 'revoke', userId: u.id })}
                            disabled={userActionMutation.isPending}
                            className="btn-secondary text-xs"
                          >
                            Revoke access
                          </button>
                        ) : (
                          <button
                            onClick={() => userActionMutation.mutate({ action: 'approve', userId: u.id })}
                            disabled={userActionMutation.isPending}
                            className="btn-primary text-xs"
                          >
                            Approve
                          </button>
                        )
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mt-3">
                    <label className="text-xs text-dark-textMuted">Orders Gmail account:</label>
                    <select
                      value={u.gmail_account || ''}
                      onChange={(e) =>
                        userActionMutation.mutate({
                          action: 'account',
                          userId: u.id,
                          account: e.target.value || null,
                        })
                      }
                      disabled={userActionMutation.isPending}
                      className="input text-xs py-1 w-auto"
                    >
                      <option value="">none</option>
                      {ingestAccounts.map((a) => {
                        const name = a.account || a.user;
                        return name ? (
                          <option key={name} value={name}>{name}</option>
                        ) : null;
                      })}
                    </select>
                    <span className="text-xs text-dark-textMuted">
                      (controls which orders they see)
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Invitation Codes (Admin Only) */}
      {user?.is_admin && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-xl font-semibold">Invitation Codes</h2>
              <p className="text-dark-textMuted text-sm">
                Generate codes for new users to register
              </p>
            </div>
            {!showCreateInvite && (
              <button onClick={() => setShowCreateInvite(true)} className="btn-primary">
                Create Invitation
              </button>
            )}
          </div>

          {showCreateInvite && (
            <form onSubmit={handleCreateInvite} className="mb-4 p-4 bg-dark-elevated rounded-lg">
              <div className="mb-3">
                <label className="block text-sm font-medium mb-2">Send to Email (optional)</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="friend@example.com"
                  className="input"
                />
              </div>
              <div className="mb-3">
                <label className="block text-sm font-medium mb-2">Note (optional)</label>
                <input
                  type="text"
                  value={inviteNote}
                  onChange={(e) => setInviteNote(e.target.value)}
                  placeholder="Who is this for?"
                  className="input"
                />
              </div>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={createInviteMutation.isPending}
                  className="btn-primary"
                >
                  {createInviteMutation.isPending ? 'Creating...' : 'Generate Code'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateInvite(false);
                    setInviteNote('');
                    setInviteEmail('');
                  }}
                  className="btn-secondary"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {invitationsLoading ? (
            <div className="flex justify-center py-6">
              <div className="w-8 h-8 border-4 border-dark-accent border-t-transparent rounded-full spinner"></div>
            </div>
          ) : (invitationsData?.invitations || []).length === 0 ? (
            <p className="text-dark-textMuted text-center py-4">
              No invitation codes yet. Create one to invite new users.
            </p>
          ) : (
            <div className="space-y-2">
              {(invitationsData?.invitations || []).map((invite) => (
                <div
                  key={invite.id}
                  className={`p-3 rounded-lg ${
                    invite.is_valid ? 'bg-dark-elevated' : 'bg-dark-surface opacity-60'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <code className="font-mono text-sm bg-dark-surface px-2 py-1 rounded">
                          {invite.code}
                        </code>
                        <button
                          onClick={() => handleCopyCode(invite.code)}
                          className="text-dark-accent hover:text-dark-accentHover p-1"
                          title="Copy code"
                        >
                          {copiedCode === invite.code ? (
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                          ) : (
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                          )}
                        </button>
                        <span
                          className={invite.is_valid ? 'chip-neutral' : 'chip-neutral opacity-60'}
                        >
                          {invite.is_valid ? 'valid' : 'used'}
                        </span>
                      </div>
                      <div className="text-xs text-dark-textMuted mt-1">
                        Created by {invite.created_by} on {fmtDate(invite.created_at)}
                        {invite.note && <span className="ml-2">· {invite.note}</span>}
                        {invite.used_by && <span className="ml-2">· Used by {invite.used_by}</span>}
                      </div>
                    </div>
                    <button
                      onClick={() => {
                        if (window.confirm('Delete this invitation code?')) {
                          deleteInviteMutation.mutate(invite.id);
                        }
                      }}
                      disabled={deleteInviteMutation.isPending}
                      className="text-dark-textMuted hover:text-dark-error p-1"
                      title="Delete invitation"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default SettingsPage;
