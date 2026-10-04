import React, { useEffect, useMemo, useState } from 'react';
import { Plug, Loader2, ShieldCheck } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { apiJson } from '../lib/api';
import { getApiUrl } from '../config';
import LoginModal from './LoginModal';

// The OAuth consent screen for MCP clients (claude.ai, ChatGPT, ...). The API
// bounced the client's /oauth/authorize request here because only the
// dashboard holds the session. Approving mints a code server-side and sends
// the browser back to the client; the access token it then receives is an
// ordinary API key, listed (and revocable) in the account page.

function readParams() {
  const hash = window.location.hash || '';
  const q = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : '';
  return Object.fromEntries(new URLSearchParams(q).entries());
}

export default function OAuthConsent() {
  const { isSignedIn, loading, me } = useAuth();
  const params = useMemo(readParams, []);
  const [client, setClient] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showLogin, setShowLogin] = useState(false);

  useEffect(() => {
    if (!params.client_id) { setError('This link is missing the client id.'); return; }
    fetch(getApiUrl(`/api/oauth/client/${encodeURIComponent(params.client_id)}`))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('Unknown client'))))
      .then(setClient)
      .catch(() => setError('This connection request comes from an unknown app. Start again from the app you are connecting.'));
  }, [params.client_id]);

  useEffect(() => {
    if (!loading && !isSignedIn) setShowLogin(true);
  }, [loading, isSignedIn]);

  const decide = async (allow) => {
    setBusy(true);
    try {
      if (!allow) {
        const u = new URL(params.redirect_uri);
        u.searchParams.set('error', 'access_denied');
        if (params.state) u.searchParams.set('state', params.state);
        window.location.replace(u.toString());
        return;
      }
      const d = await apiJson('/api/oauth/authorize', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: params.client_id,
          redirect_uri: params.redirect_uri,
          state: params.state || null,
          code_challenge: params.code_challenge,
          code_challenge_method: params.code_challenge_method || 'S256',
          scope: params.scope || null,
          response_type: params.response_type || 'code',
        }),
      });
      window.location.replace(d.redirect);
    } catch (e) {
      setError(e?.detail || 'Could not complete the connection. Try again from the app.');
      setBusy(false);
    }
  };

  const name = client?.client_name || 'an app';

  return (
    <main id="main-content" className="min-h-screen flex items-center justify-center px-4 py-10">
      <div className="card-print p-6 sm:p-8 max-w-md w-full">
        {/* the app on one end, Synapse AI on the other, a filament between */}
        <div className="flex items-center gap-3 mb-7" aria-hidden="true">
          <span className="w-11 h-11 rounded-card tray flex items-center justify-center shrink-0">
            <Plug size={18} className="text-ink" />
          </span>
          <span className="flex-1 border-t border-dashed border-rule2" />
          <img src="/logo-synapse.svg" alt="" width="44" height="44" className="w-11 h-11 shrink-0" />
        </div>

        <p className="readout mb-2">Connect an app</p>
        <h1 className="font-display text-2xl text-ink leading-tight break-words">Connect {name} to Synapse AI</h1>
        {error ? (
          <p role="alert" className="text-warn text-sm mt-4 leading-relaxed">{error}</p>
        ) : (
          <>
            <p className="text-ink2 text-sm mt-3 mb-6 leading-relaxed">
              <b className="text-ink font-medium">{name}</b> wants to clip and publish videos with your account
              {me?.email ? <> (<span className="text-ink break-all">{me.email}</span>)</> : null}.
              It will use your plan&apos;s minutes and you can disconnect it any time from
              Account → API keys.
            </p>
            <p className="readout mb-3">It will be able to</p>
            <ul className="tray p-4 text-sm text-ink2 space-y-2.5 mb-7">
              <li className="flex gap-2.5"><ShieldCheck size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> Process videos and read the resulting clips</li>
              <li className="flex gap-2.5"><ShieldCheck size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> Add subtitles, recut and publish clips you own</li>
              <li className="flex gap-2.5"><ShieldCheck size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> Nothing else: no billing, no account settings, no key management</li>
            </ul>
            {loading || !client ? (
              <div role="status" className="flex justify-center py-2">
                <Loader2 className="animate-spin text-muted" size={18} aria-hidden="true" />
                <span className="sr-only">Loading…</span>
              </div>
            ) : isSignedIn ? (
              <div className="flex flex-col-reverse sm:flex-row gap-3">
                <button type="button" onClick={() => decide(false)} disabled={busy} className="btn-ghost flex-1 py-2.5">Cancel</button>
                <button type="button" onClick={() => decide(true)} disabled={busy} aria-busy={busy || undefined} className="btn-accent flex-1 py-2.5">
                  {busy
                    ? <><Loader2 size={16} className="animate-spin" aria-hidden="true" /><span className="sr-only">Connecting…</span></>
                    : 'Allow'}
                </button>
              </div>
            ) : (
              <button type="button" onClick={() => setShowLogin(true)} className="btn-accent w-full py-2.5">Sign in to continue</button>
            )}
          </>
        )}
      </div>
      {showLogin && !isSignedIn && <LoginModal onClose={() => setShowLogin(false)} />}
    </main>
  );
}
