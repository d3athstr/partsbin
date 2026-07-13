import api from './api';

const dashboardService = {
  get: async () => {
    const response = await api.get('/dashboard');
    return response.data;
  },
};

export default dashboardService;
