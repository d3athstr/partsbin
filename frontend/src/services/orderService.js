import api from './api';

const orderService = {
  /** params: {status, vendor, page, per_page, sort, order} */
  list: async (params = {}) => {
    const clean = {};
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') clean[k] = v;
    });
    const response = await api.get('/orders', { params: clean });
    return response.data;
  },

  get: async (id) => {
    const response = await api.get(`/orders/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/orders', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/orders/${id}`, data);
    return response.data;
  },

  /**
   * Update a single order item's match:
   *   {match_status: 'confirmed' | 'ignored'}  or  {component_id: n}
   */
  updateItem: async (orderId, itemId, data) => {
    const response = await api.put(`/orders/${orderId}/items/${itemId}`, data);
    return response.data;
  },

  /** Create a new component pre-filled from an order item; auto-confirms. */
  createComponentFromItem: async (orderId, itemId, overrides = {}) => {
    const response = await api.post(
      `/orders/${orderId}/items/${itemId}/create-component`,
      overrides
    );
    return response.data;
  },

  /** Claude-infer + create components for all pending items on an order. */
  autoCreateComponents: async (orderId) => {
    const response = await api.post(`/orders/${orderId}/auto-create-components`);
    return response.data;
  },

  /** Mark order received; confirmed items get +qty transactions. */
  receive: async (orderId) => {
    const response = await api.post(`/orders/${orderId}/receive`);
    return response.data;
  },

  /** Count + items across orders needing match/receive. */
  pendingReview: async () => {
    const response = await api.get('/review/pending');
    return response.data;
  },
};

export default orderService;
