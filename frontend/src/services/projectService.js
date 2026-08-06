import api from './api';

const projectService = {
  /** params: {search, status, tag, page, per_page, sort, order} */
  list: async (params = {}) => {
    const clean = {};
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') clean[k] = v;
    });
    const response = await api.get('/projects', { params: clean });
    return response.data;
  },

  get: async (id) => {
    const response = await api.get(`/projects/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/projects', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/projects/${id}`, data);
    return response.data;
  },

  remove: async (id) => {
    const response = await api.delete(`/projects/${id}`);
    return response.data;
  },

  // ==================== BOM ====================

  addBomLine: async (projectId, { component_id, qty_planned, note, est_unit_cost }) => {
    const response = await api.post(`/projects/${projectId}/bom`, {
      component_id,
      qty_planned,
      note: note || undefined,
      est_unit_cost: est_unit_cost === undefined ? undefined : est_unit_cost,
    });
    return response.data;
  },

  updateBomLine: async (projectId, lineId, data) => {
    const response = await api.put(`/projects/${projectId}/bom/${lineId}`, data);
    return response.data;
  },

  deleteBomLine: async (projectId, lineId) => {
    const response = await api.delete(`/projects/${projectId}/bom/${lineId}`);
    return response.data;
  },

  /** Decrements stock via a project_use transaction. */
  consume: async (projectId, lineId, qty) => {
    const response = await api.post(
      `/projects/${projectId}/bom/${lineId}/consume`,
      { qty }
    );
    return response.data;
  },

  // ==================== Files ====================

  uploadFile: async (projectId, file, kind = 'other') => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('kind', kind);
    const response = await api.post(`/projects/${projectId}/files`, formData);
    return response.data;
  },

  deleteFile: async (projectId, fileId) => {
    const response = await api.delete(`/projects/${projectId}/files/${fileId}`);
    return response.data;
  },
};

export default projectService;
