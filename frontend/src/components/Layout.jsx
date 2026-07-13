import { useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import orderService from '../services/orderService';

const NavIcon = ({ path }) => (
  <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={path} />
  </svg>
);

const NAV_ITEMS = [
  {
    to: '/',
    label: 'Dashboard',
    icon: 'M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z',
  },
  {
    to: '/inventory',
    label: 'Inventory',
    icon: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
  },
  {
    to: '/projects',
    label: 'Projects',
    icon: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
  },
  {
    to: '/orders',
    label: 'Orders',
    icon: 'M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z',
    badge: true,
  },
  {
    to: '/settings',
    label: 'Settings',
    icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
  },
];

const Layout = ({ children }) => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Pending order-review count for the Orders badge
  const { data: pendingData } = useQuery({
    queryKey: ['reviewPending'],
    queryFn: () => orderService.pendingReview(),
    refetchInterval: 60 * 1000,
    staleTime: 30 * 1000,
  });
  const pendingCount = pendingData?.count ?? 0;

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const navLinks = (
    <nav className="flex-1 px-3 py-4 space-y-1">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          onClick={() => setMobileOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              isActive
                ? 'bg-dark-elevated text-dark-text'
                : 'text-dark-textMuted hover:bg-dark-elevated hover:text-dark-text'
            }`
          }
        >
          <NavIcon path={item.icon} />
          <span className="flex-1">{item.label}</span>
          {item.badge && pendingCount > 0 && (
            <span className="chip-warn">{pendingCount}</span>
          )}
        </NavLink>
      ))}
    </nav>
  );

  const brand = (
    <Link to="/" className="flex items-center gap-2 px-4 h-16 border-b border-dark-border">
      <svg className="w-7 h-7 text-dark-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <rect x="7" y="7" width="10" height="10" rx="1" strokeWidth={2} />
        <rect x="10.5" y="10.5" width="3" height="3" strokeWidth={2} />
        <path strokeLinecap="round" strokeWidth={2} d="M9 7V4m3 3V4m3 3V4M9 20v-3m3 3v-3m3 3v-3M7 9H4m3 3H4m3 3H4m16-6h-3m3 3h-3m3 3h-3" />
      </svg>
      <span className="text-lg font-bold text-dark-text">PartsBin</span>
    </Link>
  );

  const userSection = (
    <div className="px-4 py-4 border-t border-dark-border">
      <div className="flex items-center justify-between">
        <span className="text-sm text-dark-textMuted truncate">{user?.username}</span>
        <button
          onClick={handleLogout}
          className="text-sm text-dark-textMuted hover:text-dark-text transition-colors"
        >
          Logout
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-dark-bg">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:flex-col fixed inset-y-0 left-0 w-56 bg-dark-surface border-r border-dark-border">
        {brand}
        {navLinks}
        {userSection}
      </aside>

      {/* Mobile top bar */}
      <div className="md:hidden sticky top-0 z-40 flex items-center justify-between h-14 px-4 bg-dark-surface border-b border-dark-border">
        <Link to="/" className="flex items-center gap-2">
          <svg className="w-6 h-6 text-dark-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <rect x="7" y="7" width="10" height="10" rx="1" strokeWidth={2} />
            <rect x="10.5" y="10.5" width="3" height="3" strokeWidth={2} />
          </svg>
          <span className="font-bold">PartsBin</span>
        </Link>
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="p-2 text-dark-textMuted hover:text-dark-text"
          aria-label="Toggle menu"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {mobileOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-30" onClick={() => setMobileOpen(false)}>
          <div className="absolute inset-0 bg-black bg-opacity-50" />
          <div
            className="absolute top-14 left-0 bottom-0 w-64 bg-dark-surface border-r border-dark-border flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {navLinks}
            {userSection}
          </div>
        </div>
      )}

      {/* Main content */}
      <main className="md:pl-56">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
          {children}
        </div>
      </main>
    </div>
  );
};

export default Layout;
