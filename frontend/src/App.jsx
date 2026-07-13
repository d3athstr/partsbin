import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';

// Pages
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import InventoryPage from './pages/InventoryPage';
import ComponentDetailPage from './pages/ComponentDetailPage';
import ComponentCreatePage from './pages/ComponentCreatePage';
import ComponentEditPage from './pages/ComponentEditPage';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import ProjectCreatePage from './pages/ProjectCreatePage';
import ProjectEditPage from './pages/ProjectEditPage';
import OrdersPage from './pages/OrdersPage';
import OrderDetailPage from './pages/OrderDetailPage';
import SettingsPage from './pages/SettingsPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 60 * 1000,
    },
  },
});

const Protected = ({ children }) => (
  <ProtectedRoute>
    <Layout>{children}</Layout>
  </ProtectedRoute>
);

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />

            {/* Protected routes */}
            <Route path="/" element={<Protected><Dashboard /></Protected>} />

            <Route path="/inventory" element={<Protected><InventoryPage /></Protected>} />
            <Route path="/inventory/new" element={<Protected><ComponentCreatePage /></Protected>} />
            <Route path="/inventory/:id" element={<Protected><ComponentDetailPage /></Protected>} />
            <Route path="/inventory/:id/edit" element={<Protected><ComponentEditPage /></Protected>} />

            <Route path="/projects" element={<Protected><ProjectsPage /></Protected>} />
            <Route path="/projects/new" element={<Protected><ProjectCreatePage /></Protected>} />
            <Route path="/projects/:id" element={<Protected><ProjectDetailPage /></Protected>} />
            <Route path="/projects/:id/edit" element={<Protected><ProjectEditPage /></Protected>} />

            <Route path="/orders" element={<Protected><OrdersPage /></Protected>} />
            <Route path="/orders/:id" element={<Protected><OrderDetailPage /></Protected>} />

            <Route path="/settings" element={<Protected><SettingsPage /></Protected>} />

            {/* Catch all */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
