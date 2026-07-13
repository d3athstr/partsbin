import api from './api';

const ingestService = {
  /** Per-Gmail-account token/poll status. */
  status: async () => {
    const response = await api.get('/ingest/status');
    return response.data;
  },

  /** Manual ingest trigger (admin). */
  run: async () => {
    const response = await api.post('/ingest/run');
    return response.data;
  },
};

export default ingestService;
