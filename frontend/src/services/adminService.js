import api from './api';

/**
 * Admin invitation management (per API.md: GET/POST /api/admin/invitations,
 * DELETE /api/admin/invitations/<id>).
 */
const adminService = {
  getInvitations: async () => {
    const response = await api.get('/admin/invitations');
    return response.data;
  },

  createInvitation: async (options = {}) => {
    const response = await api.post('/admin/invitations', options);
    return response.data;
  },

  deleteInvitation: async (invitationId) => {
    const response = await api.delete(`/admin/invitations/${invitationId}`);
    return response.data;
  },
};

// ==================== User management ====================

adminService.getUsers = async () => {
  const response = await api.get('/admin/users');
  return response.data;
};

adminService.approveUser = async (userId) => {
  const response = await api.put(`/admin/users/${userId}/approve`);
  return response.data;
};

adminService.revokeUser = async (userId) => {
  const response = await api.put(`/admin/users/${userId}/revoke`);
  return response.data;
};

adminService.setGmailAccount = async (userId, account) => {
  const response = await api.put(`/admin/users/${userId}/gmail-account`, { account });
  return response.data;
};

adminService.deleteUser = async (userId) => {
  const response = await api.delete(`/admin/users/${userId}`);
  return response.data;
};

export default adminService;
