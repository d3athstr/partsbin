import api from './api';

const componentService = {
  /**
   * List components.
   * params: {search, category, tag, location, low_stock, out_of_stock,
   *          page, per_page, sort, order}
   */
  list: async (params = {}) => {
    const clean = {};
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '' && v !== false) clean[k] = v;
    });
    const response = await api.get('/components', { params: clean });
    return response.data;
  },

  get: async (id) => {
    const response = await api.get(`/components/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/components', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/components/${id}`, data);
    return response.data;
  },

  remove: async (id) => {
    const response = await api.delete(`/components/${id}`);
    return response.data;
  },

  /** Manual stock adjustment: creates a transaction. */
  adjust: async (id, delta, note = '') => {
    const response = await api.post(`/components/${id}/adjust`, {
      delta,
      note: note || undefined,
    });
    return response.data;
  },

  uploadImage: async (id, file) => {
    const formData = new FormData();
    formData.append('image', file);
    const response = await api.post(`/components/${id}/image`, formData);
    return response.data;
  },

  /** Draft a component from a product-page URL (Amazon/AliExpress/...). */
  fromUrl: async (url) => {
    const response = await api.post('/components/from-url', { url });
    return response.data;
  },

  /** Download one of the draft's candidate images onto a component. */
  attachImage: async (id, urls) => {
    const response = await api.post(`/components/${id}/attach-image`, { urls });
    return response.data;
  },

  /** Web-search image/datasheet/missing metadata for a component. */
  enrich: async (id) => {
    const response = await api.post(`/components/${id}/enrich`);
    return response.data;
  },

  transactions: async (id) => {
    const response = await api.get(`/components/${id}/transactions`);
    return response.data;
  },

  categories: async () => {
    const response = await api.get('/categories');
    return response.data;
  },

  locations: async () => {
    const response = await api.get('/locations');
    return response.data;
  },

  tags: async () => {
    const response = await api.get('/tags');
    return response.data;
  },

  createTag: async (name) => {
    const response = await api.post('/tags', { name });
    return response.data;
  },
};

export default componentService;
