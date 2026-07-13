import axios from 'axios';

// Create axios instance with default config
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  withCredentials: true, // Important for cookie-based sessions
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
api.interceptors.request.use(
  (config) => {
    // Remove Content-Type for FormData so browser sets it with boundary
    if (config.data instanceof FormData) {
      delete config.headers['Content-Type'];
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const { status } = error.response;
      if (status === 401) {
        // Unauthorized - redirect to login (except for auth pages)
        if (
          !window.location.pathname.includes('/login') &&
          !window.location.pathname.includes('/register')
        ) {
          window.location.href = '/login';
        }
      }
    } else if (error.request) {
      console.error('Network error - server not responding');
    }
    return Promise.reject(error);
  }
);

/**
 * Normalize list-ish responses. Backend list endpoints return
 * {items, total, page, per_page}, but small lookup endpoints
 * (categories/locations/tags) may return a bare array or a keyed object.
 */
export const asList = (data, ...keys) => {
  if (Array.isArray(data)) return data;
  if (!data) return [];
  for (const key of keys) {
    if (Array.isArray(data[key])) return data[key];
  }
  if (Array.isArray(data.items)) return data.items;
  return [];
};

export const errMsg = (err, fallback = 'Request failed') =>
  err?.response?.data?.error || err?.message || fallback;

export default api;
