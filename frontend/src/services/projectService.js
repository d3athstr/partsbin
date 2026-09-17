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

  // ==================== Assembly order ====================
  //
  // Every one of these returns the re-checked assembly report, not just the
  // step that changed: moving or editing a step is exactly what creates or
  // clears an access conflict, so the caller is always handed the new verdict.

  getAssembly: async (projectId) => {
    const response = await api.get(`/projects/${projectId}/assembly`);
    return response.data;
  },

  addAssemblyStep: async (projectId, data) => {
    const response = await api.post(`/projects/${projectId}/assembly`, data);
    return response.data;
  },

  updateAssemblyStep: async (projectId, stepId, data) => {
    const response = await api.put(`/projects/${projectId}/assembly/${stepId}`, data);
    return response.data;
  },

  deleteAssemblyStep: async (projectId, stepId) => {
    const response = await api.delete(`/projects/${projectId}/assembly/${stepId}`);
    return response.data;
  },

  /** order: the complete list of step ids in their new order. */
  reorderAssembly: async (projectId, order) => {
    const response = await api.post(`/projects/${projectId}/assembly/reorder`, { order });
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
