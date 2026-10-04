import { StrictMode, useState, useEffect, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Landing from './Landing.jsx'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { capture as captureAttribution } from './lib/attribution'
import PricingPage from './components/PricingPage'
import AccountPage from './components/AccountPage'
import LoginModal from './components/LoginModal'
import { applyConsent } from './lib/consent'
import CookieBanner from './components/CookieBanner'

const App = lazy(() => import('./App.jsx'))
const Legal = lazy(() => import('./Legal.jsx'))
const OAuthConsent = lazy(() => import('./components/OAuthConsent'))

function PageShell({ title, children }) {
  return (
    <div className="min-h-screen text-ink2">
      <header className="sticky top-0 z-20 bg-paper border-b border-rule">
        <div className="max-w-7xl mx-auto h-14 sm:h-16 flex items-center justify-between gap-3 px-4 sm:px-8">
          <a href="#app" className="flex items-center gap-2.5 min-h-[44px] min-w-0" aria-label="Synapse AI, open the app">
            <img src="/logo-synapse.svg" alt="" width="28" height="28" className="w-7 h-7 shrink-0" />
            <span className="brand-word text-lg truncate">Synapse <span className="brand-ai">AI</span></span>
          </a>
          <a href="#app" className="btn-ghost px-3.5 py-2 shrink-0">
            <span aria-hidden="true">←</span> Back to app
          </a>
        </div>
      </header>
      <main id="main-content" className="px-4 py-8 sm:px-8 sm:py-12 pb-[max(2.5rem,env(safe-area-inset-bottom))]">
        {title && <h1 className="page-title text-center mb-6 sm:mb-10">{title}</h1>}
        {children}
      </main>
    </div>
  );
}

function PricingView() {
  const [showLogin, setShowLogin] = useState(false);
  return (
    <PageShell>
      <PricingPage onRequireLogin={() => setShowLogin(true)} />
      {showLogin && <LoginModal onClose={() => setShowLogin(false)} />}
    </PageShell>
  );
}

function AccountView() {
  const { isSignedIn, loading } = useAuth();
  useEffect(() => {
    if (!loading && !isSignedIn) window.location.hash = '#/pricing';
  }, [loading, isSignedIn]);
  return <PageShell><AccountPage /></PageShell>;
}

// Landing spot after an account is erased. Its own view because the session is
// gone: sending the user to #/account would bounce them to pricing with no
// explanation, and "openshorts_skip_landing" would send them into the app.
function DeletedView() {
  return (
    <main id="main-content" className="min-h-screen text-ink2 flex items-center justify-center p-4 sm:p-8">
      <div className="card-print max-w-md w-full p-6 sm:p-8 space-y-4">
        <img src="/logo-synapse.svg" alt="" width="40" height="40" className="w-10 h-10" />
        <p className="readout">Account</p>
        <h1 className="page-title">Your account is deleted</h1>
        <p className="text-sm leading-relaxed">
          Your projects, clips and transcripts are gone, any subscription is
          cancelled, and your API keys no longer work. We've emailed you a
          confirmation with the details.
        </p>
        <p className="text-sm text-muted leading-relaxed">
          You're welcome back any time — signing up again with the same address
          starts a brand-new, empty account.
        </p>
        <a href="#landing" className="btn-ghost px-4 py-2 inline-flex">Back to Synapse AI</a>
      </div>
    </main>
  );
}

function Root() {
  const resolveView = () => {
    const hash = window.location.hash || '';
    if (hash.startsWith('#/auth/')) return 'auth';       // AuthContext consumes then redirects
    if (hash.startsWith('#/oauth/authorize')) return 'oauth';
    if (hash.startsWith('#/account')) return 'account';
    if (hash.startsWith('#/deleted')) return 'deleted';
    if (hash.startsWith('#/pricing')) return 'pricing';
    if (hash === '#legal') return 'legal';
    // #landing = explicit landing view (app logo); section anchors keep the landing mounted
    if (['#landing', '#features', '#how-it-works', '#pricing', '#comparison', '#faq'].includes(hash)) return 'landing';
    if (hash === '#app' || hash.startsWith('#app?') || localStorage.getItem('openshorts_skip_landing') === '1') return 'app';
    return 'landing';
  };

  const [view, setView] = useState(resolveView);

  useEffect(() => {
    const handleHashChange = () => setView(resolveView());
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleLaunchApp = () => {
    localStorage.setItem('openshorts_skip_landing', '1');
    window.location.hash = '#app';
    setView('app');
  };

  if (view === 'legal') return <Legal />;
  if (view === 'pricing') return <PricingView />;
  if (view === 'account') return <AccountView />;
  if (view === 'oauth') return <OAuthConsent />;
  if (view === 'deleted') return <DeletedView />;
  if (view === 'auth') {
    return <div role="status" className="min-h-screen flex items-center justify-center text-muted text-sm">Signing you in…</div>;
  }
  if (view === 'app') return <App />;
  return <Landing onLaunchApp={handleLaunchApp} />;
}

// Before React mounts: AuthContext rewrites the URL on auth redirects, which
// would destroy the referrer and any UTM params we still need to read.
captureAttribution();

// Start whatever the visitor previously agreed to. Nothing at all on a first
// visit: index.html only publishes the analytics initialiser, it never runs it.
applyConsent();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <Suspense fallback={<div role="status" className="min-h-screen flex items-center justify-center text-muted text-sm">Loading…</div>}>
        <Root />
      </Suspense>
      <CookieBanner />
    </AuthProvider>
  </StrictMode>,
)
