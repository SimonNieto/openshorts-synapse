import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, CreditCard, LogOut, Plus, AlertTriangle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { apiJson } from '../lib/api';
import { track } from '../lib/analytics';
import ApiKeysCard from './ApiKeysCard';
import McpConnectCard from './McpConnectCard';
import DeleteAccountCard from './DeleteAccountCard';
import SocialAnalyticsCard from './SocialAnalyticsCard';
import InvoicesCard from './InvoicesCard';

const fmt1 = (n) => Math.round((n || 0) * 10) / 10;

// Mirrors cloud/config.BILLING_ATTENTION_STATES: states where the customer has
// to do something (fix a card, finish a payment) before minutes come back.
const PAYMENT_ISSUE_STATES = ['past_due', 'unpaid', 'incomplete', 'paused'];

// Account/billing page: plan, usage meter, top-ups, manage billing, logout.
export default function AccountPage() {
  const { me, refreshMe, logout, plan, minutes } = useAuth();
  const [busy, setBusy] = useState(false);
  const [topups, setTopups] = useState([]);
  const [activating, setActivating] = useState(false);

  // After returning from Checkout the webhook may lag — poll /api/me briefly.
  useEffect(() => {
    const hash = window.location.hash || '';
    if (!hash.includes('checkout=success')) return;
    setActivating(true);
    let tries = 0;
    const t = setInterval(async () => {
      tries += 1;
      const data = await refreshMe();
      // 'free' is the default plan for any signed-in account, so it does NOT
      // mean the checkout landed — keep polling until the webhook writes the
      // paid subscription.
      const paidPlan = data?.plan && data.plan !== 'free';
      if (paidPlan || tries > 15) {
        clearInterval(t);
        setActivating(false);
        // Fire the Subscribed conversion goal. A pending-checkout stash (set in
        // PricingSection) carries the plan price, so we can attach real revenue;
        // top-ups don't set it, so they never count as a subscription.
        if (paidPlan) {
          let pending = null;
          try { pending = JSON.parse(localStorage.getItem('os_pending_checkout') || 'null'); } catch (_) { /* ignore */ }
          if (pending) {
            // This Plausible is Community Edition, which has no revenue goals —
            // so the price rides along as plain props (value_usd / plan) that CE
            // can break the goal down by. The exact MRR still lives in Stripe.
            track('Subscribed', {
              props: {
                plan: pending.plan,
                interval: pending.interval,
                value_usd: Math.round((pending.amount || 0) / 100),
              },
            });
            try { localStorage.removeItem('os_pending_checkout'); } catch (_) { /* ignore */ }
          }
        }
        // First time a plan activates, take the user straight to connect their
        // socials. Guard with a flag so top-up checkouts don't re-trigger it.
        if (paidPlan && !localStorage.getItem('os_socials_prompted')) {
          localStorage.setItem('os_socials_prompted', '1');
          try {
            const { access_url } = await apiJson('/api/social/connect', { method: 'POST' });
            if (access_url) { window.location.href = access_url; return; }
          } catch (_) { /* fall through to the account page */ }
        }
        window.location.hash = '#/account';
      }
    }, 2000);
    return () => clearInterval(t);
  }, [refreshMe]);

  useEffect(() => {
    apiJson('/api/billing/plans').then((d) => setTopups(d.topups || [])).catch(() => {});
  }, []);

  const openPortal = useCallback(async () => {
    setBusy(true);
    try {
      const { url } = await apiJson('/api/billing/portal', { method: 'POST' });
      window.location.href = url;
    } catch (e) { setBusy(false); alert('Could not open billing portal.'); }
  }, []);

  const buyTopup = useCallback(async (price_id) => {
    setBusy(true);
    try {
      const { url } = await apiJson('/api/billing/checkout', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ price_id }),
      });
      window.location.href = url;
    } catch (e) { setBusy(false); alert(e?.detail || 'Could not start checkout.'); }
  }, []);

  if (!me) {
    return (
      <div role="status" className="flex justify-center py-16">
        <Loader2 className="animate-spin text-muted" aria-hidden="true" />
        <span className="sr-only">Loading your account…</span>
      </div>
    );
  }

  const m = minutes || {};
  const total = (m.plan_allowance || 0) + (m.topup_remaining || 0) + (m.plan_used || 0);
  const usedPct = total > 0 ? Math.min(100, ((m.plan_used || 0) / (m.plan_allowance || 1)) * 100) : 0;
  const low = total > 0 && (m.remaining || 0) <= total * 0.2;

  return (
    <div className="max-w-2xl mx-auto space-y-12">
      <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="eyebrow mb-2">Account</p>
          <h1 className="page-title">Your account</h1>
          <p className="text-muted text-sm mt-2 break-all">{me.user?.email}</p>
        </div>
        <button type="button" onClick={logout} className="btn-quiet shrink-0 self-start sm:self-auto">
          <LogOut size={16} aria-hidden="true" /> Sign out
        </button>
      </header>

      {activating && (
        <div role="status" aria-live="polite" className="tray px-4 py-3 text-sm text-ink2 flex items-center gap-2.5">
          <Loader2 size={16} className="animate-spin text-muted" aria-hidden="true" /> Activating your plan…
        </div>
      )}

      <section aria-labelledby="account-plan-title" className="space-y-5">
        <h2 id="account-plan-title" className="font-display text-xl text-ink">Plan and usage</h2>

        <div className="card-print p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="readout mb-1.5">Current plan</p>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-display text-xl text-ink first-letter:uppercase">{plan ? `${plan} plan` : 'No active plan'}</h3>
                {/* Payment-issue states get the explanatory banner below instead —
                    showing raw Stripe jargon ("past_due") twice explains nothing. */}
                {me.status && me.status !== 'active'
                  && !PAYMENT_ISSUE_STATES.includes(me.status) && (
                  <span className="badge-warn">{me.status}</span>
                )}
                {me.cancel_at_period_end && (
                  <span className="badge-warn">Cancels at period end</span>
                )}
              </div>
            </div>
            {/* Any Stripe relationship — live OR broken (past_due, unpaid) — must
                keep the portal reachable. A declined card demotes `plan` to free,
                so keying this off the plan alone hid the one button that fixes it. */}
            {me.has_billing_account ? (
              <button type="button" onClick={openPortal} disabled={busy} className="btn-ghost px-4 py-2 shrink-0">
                <CreditCard size={16} aria-hidden="true" /> Manage billing
              </button>
            ) : (
              <button type="button" onClick={() => { window.location.hash = '#/pricing'; }} className="btn-accent px-4 py-2 shrink-0">
                Upgrade
              </button>
            )}
          </div>

          {/* A bare "past_due" chip explains nothing. Say what happened and what
              fixes it — this is the whole reason the account reads as free. */}
          {PAYMENT_ISSUE_STATES.includes(me.status) && (
            <div className="mt-5 rounded-card border border-warn/40 bg-warn/5 p-4 text-sm text-ink2 flex items-start gap-3">
              <AlertTriangle size={16} className="text-warn shrink-0 mt-0.5" aria-hidden="true" />
              <p className="leading-relaxed">
                <b className="text-ink">We couldn't charge your card.</b>{' '}
                {me.status === 'incomplete'
                  ? 'Your payment was never completed, so the plan never started.'
                  : 'Your plan is paused and you\'re on free minutes until it goes through.'}{' '}
                <button type="button" onClick={openPortal} disabled={busy}
                        className="text-ink underline decoration-ink/40 underline-offset-2 hover:decoration-current">
                  Update your card
                </button>{' '}
                and it resumes right away.
              </p>
            </div>
          )}

          <div className="mt-6 pt-6 border-t border-rule">
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
              <p className="flex items-baseline gap-2">
                <span className="font-quote text-5xl text-ink leading-none tabular-nums">{fmt1(m.remaining)}</span>
                <span className="text-sm text-muted">min remaining in total</span>
              </p>
              {low && <span className="badge-warn">Running low</span>}
            </div>

            <dl className="mt-6 space-y-3 text-sm">
              <div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted">Plan minutes</dt>
                  <dd className="text-ink2 tabular-nums">{fmt1(m.plan_used)} / {fmt1(m.plan_allowance)} used</dd>
                </div>
                <div
                  className="mt-2 h-1.5 bg-paper3 rounded-full overflow-hidden"
                  role="progressbar"
                  aria-label="Plan minutes used"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(usedPct)}
                >
                  <div className={`h-full transition-all ${low ? 'bg-warn' : 'bg-ink'}`} style={{ width: `${usedPct}%` }} />
                </div>
              </div>
              <div className="flex justify-between gap-4 pt-1">
                <dt className="text-muted">Top-up minutes</dt>
                <dd className="text-ink2 tabular-nums">{fmt1(m.topup_remaining)} remaining</dd>
              </div>
            </dl>
          </div>
        </div>

        {topups.length > 0 && (
          <section aria-labelledby="account-topups-title" className="card p-5 sm:p-6">
            <h3 id="account-topups-title" className="font-display text-lg text-ink mb-1 flex items-center gap-2">
              <Plus size={16} className="text-muted" aria-hidden="true" /> Buy more minutes
            </h3>
            <p className="text-muted text-sm mb-4">Top-ups never expire while your plan is active.</p>
            <ul className="grid grid-cols-2 gap-3">
              {topups.map((t) => (
                <li key={t.price_id}>
                  <button type="button" onClick={() => buyTopup(t.price_id)} disabled={busy}
                    className="w-full h-full tray card-hover p-4 text-left disabled:opacity-50 disabled:pointer-events-none">
                    <span className="block font-quote text-3xl text-ink leading-none tabular-nums">+{t.minutes}<span className="text-sm text-muted ml-1">min</span></span>
                    <span className="block readout mt-2">
                      {new Intl.NumberFormat('en-US', { style: 'currency', currency: (t.currency || 'usd').toUpperCase(), maximumFractionDigits: 0 }).format((t.amount || 0) / 100)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Only accounts that ever had a Stripe relationship can have invoices. */}
        {me.has_billing_account && <InvoicesCard />}

        <SocialAnalyticsCard />
      </section>

      <section aria-labelledby="account-agents-title" className="space-y-5">
        <h2 id="account-agents-title" className="font-display text-xl text-ink">Agents and API</h2>
        <McpConnectCard cloud />
        <ApiKeysCard />
      </section>

      <section aria-labelledby="account-danger-title" className="space-y-5">
        <h2 id="account-danger-title" className="font-display text-xl text-ink">Close your account</h2>
        <DeleteAccountCard />
      </section>
    </div>
  );
}
