import React, { useState, useRef, useCallback } from 'react';
import { Trash2, AlertTriangle, Loader2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { apiJson } from '../lib/api';

// Mirrors cloud/account.DELETION_REASONS. A closed list rather than a text
// box, because the answer is stored in a record that outlives the account and
// free text is how personal data gets into one by accident.
const REASONS = [
  ['too_expensive', 'Too expensive'],
  ['not_using_it', "I'm not using it"],
  ['clip_quality', "The clips weren't good enough"],
  ['missing_feature', 'Missing a feature I need'],
  ['found_alternative', 'I found something better'],
  ['privacy', 'Privacy concerns'],
  ['other', 'Something else'],
];

// GDPR Art. 17 erasure, self-service (backend: cloud/account.py). The privacy
// policy tells users they can delete their account from the dashboard, so this
// has to be findable — but it is also irreversible, hence: collapsed by
// default, an itemised list of what actually goes, and typing the account email
// as the confirmation step (there is no password to re-enter; sign-in is a
// magic link).
export default function DeleteAccountCard() {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // setBusy only disables the button on the next render, which a fast double
  // click beats. The server survives a duplicate call, but each one re-runs a
  // Stripe cancel and an R2 prefix delete for nothing.
  const sending = useRef(false);

  const email = me?.user?.email || '';
  // `!!email` matters: without it an account page rendered before /api/me
  // resolves would treat an empty box as a match and arm the delete button.
  const matches = !!email && confirm.trim().toLowerCase() === email.toLowerCase();

  const remove = useCallback(async () => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError('');
    try {
      await apiJson('/api/account', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm_email: confirm.trim(), reason: reason || undefined }),
      });
      // The session token now points at nothing. Drop it before navigating, or
      // the landing page spends a request discovering that for itself. The
      // funnel flags go too: they are the only reason a re-signup with the same
      // address would behave like a returning user rather than a fresh one.
      logout();
      try {
        localStorage.removeItem('os_socials_prompted');
        localStorage.removeItem('os_pending_checkout');
      } catch (_) { /* ignore */ }
      window.location.hash = '#/deleted';
      window.location.reload();
    } catch (e) {
      setError(e?.detail || 'Could not delete your account. Please try again or email info@openshorts.app.');
      sending.current = false;
      setBusy(false);
    }
  }, [confirm, reason, logout]);

  return (
    <section aria-labelledby="delete-account-title" className="card p-5 sm:p-6">
      <h3 id="delete-account-title" className="font-display text-lg text-ink mb-1 flex items-center gap-2">
        <Trash2 size={16} className="text-muted" aria-hidden="true" /> Delete account
      </h3>
      <p className="text-muted text-sm leading-relaxed">
        Close your Synapse AI account and erase everything we hold about you. This
        cannot be undone.
      </p>

      {!open ? (
        <button type="button" onClick={() => setOpen(true)} className="btn-danger px-4 py-2 mt-5">
          <Trash2 size={16} aria-hidden="true" /> Delete my account
        </button>
      ) : (
        <div className="mt-5 space-y-5">
          <div className="rounded-card border border-danger/40 bg-danger/5 p-4 text-sm text-ink2 leading-relaxed">
            <p className="flex items-start gap-2 text-ink">
              <AlertTriangle size={16} className="text-danger shrink-0 mt-0.5" aria-hidden="true" />
              <b className="font-semibold">This is permanent. There is no recovery.</b>
            </p>
            <p className="mt-3">Deleted immediately:</p>
            <ul className="list-disc marker:text-muted pl-5 mt-1 space-y-0.5">
              <li>your account and sign-in</li>
              <li>every project, clip and transcript, here and in our storage</li>
              <li>your API keys, so anything using them stops working</li>
              <li>the link to any social accounts you connected</li>
            </ul>
            <p className="mt-3">
              Any active subscription is cancelled as part of this. We keep your
              invoices for six years because Spanish law requires it, plus a
              one-way hash of your email address, instead of the address, as
              proof the deletion happened.
            </p>
          </div>

          <div>
            <label htmlFor="delete-reason" className="block text-sm text-ink2 mb-1.5">Why are you leaving? <span className="text-muted">(optional)</span></label>
            <select
              id="delete-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="input-field w-full text-sm"
            >
              <option value="">Prefer not to say</option>
              {REASONS.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="delete-confirm" className="block text-sm text-ink2 mb-1.5">
              Type <b className="text-ink font-semibold break-all">{email}</b> to confirm
            </label>
            <input
              id="delete-confirm"
              value={confirm}
              onChange={(e) => { setConfirm(e.target.value); setError(''); }}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? 'delete-error' : undefined}
              className="input-field w-full text-sm"
            />
          </div>

          {error && <p id="delete-error" role="alert" className="text-sm text-danger">{error}</p>}

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={remove} disabled={!matches || busy} aria-busy={busy || undefined} className="btn-danger px-4 py-2">
              {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Trash2 size={16} aria-hidden="true" />}
              {busy ? 'Deleting…' : 'Permanently delete my account'}
            </button>
            <button type="button" onClick={() => { setOpen(false); setConfirm(''); setError(''); }}
                    disabled={busy} className="btn-quiet">
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
