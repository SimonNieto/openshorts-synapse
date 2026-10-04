import React, { useState, useEffect } from 'react';
import { Loader2, Rocket, CheckCircle2 } from 'lucide-react';
import { apiJson } from '../lib/api';
import Modal from './ui/Modal';

// Shown when a TRIALING user hits the trial minute cap. Lets them end the trial
// and activate the paid plan right away (charges the card now, unlocks the full
// monthly minutes). The subscription webhook flips status→active server-side.
export default function TrialUpgradeModal({ plan, onActivated, onClose }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const [planMinutes, setPlanMinutes] = useState(null);

  // Look up the full monthly minutes for the current plan (to show what unlocks).
  useEffect(() => {
    apiJson('/api/billing/plans')
      .then((d) => {
        const match = (d.plans || []).find((p) => p.plan === plan && p.interval === 'month');
        if (match) setPlanMinutes(match.minutes);
      })
      .catch(() => {});
  }, [plan]);

  const activate = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await apiJson('/api/billing/end-trial', { method: 'POST' });
      // Poll /api/me until the webhook flips the subscription to active.
      let ok = res?.status === 'active';
      for (let i = 0; i < 10 && !ok; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const me = await onActivated();
        ok = me?.status === 'active';
      }
      if (ok) {
        setDone(true);
        setTimeout(onClose, 1800);
      } else {
        // Charge is processing (or card needs attention) — let them proceed anyway.
        await onActivated();
        setError('Almost there — your plan is activating. If it doesn\'t unlock in a minute, check your billing details.');
      }
    } catch (e) {
      setError('Could not activate your plan. Please try again or manage billing from your account.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal isOpen onClose={onClose} eyebrow="Trial" size="md">
      {done ? (
        <div role="status" aria-live="polite" className="text-center py-4">
          <span className="inline-flex p-3 tray rounded-full text-ok mb-4"><CheckCircle2 size={24} aria-hidden="true" /></span>
          <h2 className="font-display text-xl text-ink mb-1.5">You're all set</h2>
          <p className="text-muted text-sm leading-relaxed">Your plan is active{planMinutes ? ` with ${planMinutes} minutes` : ''}. Go ahead and generate your clips.</p>
        </div>
      ) : (
        <>
          <span className="inline-flex p-3 tray rounded-full text-ink mb-4" aria-hidden="true"><Rocket size={24} /></span>
          <h2 className="font-display text-xl text-ink mb-2">You've used your free trial minutes</h2>
          <p className="text-ink2 text-sm mb-6 leading-relaxed">
            Activate your{plan ? <> <span className="capitalize font-medium text-ink">{plan}</span></> : ''} plan now to unlock{' '}
            {planMinutes ? <><b className="text-ink font-medium">{planMinutes} minutes</b> every month</> : 'your full monthly minutes'} and keep creating.
            Your card is charged today and your 3-day trial ends now.
          </p>

          {error && <p role="alert" className="text-warn text-sm mb-4 leading-relaxed">{error}</p>}

          <button
            type="button"
            onClick={activate}
            disabled={busy}
            aria-busy={busy || undefined}
            className="btn-accent w-full"
          >
            {busy ? <><Loader2 size={18} className="animate-spin" aria-hidden="true" /> Activating…</> : <>Activate my plan now</>}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="w-full mt-2 min-h-[44px] text-muted hover:text-ink text-sm py-2 disabled:opacity-60 transition-colors"
          >
            Maybe later
          </button>
        </>
      )}
    </Modal>
  );
}
