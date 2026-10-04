import React, { useState, useEffect } from 'react';
import { Loader2, Check, Zap, Clock } from 'lucide-react';
import { apiJson } from '../lib/api';
import { track } from '../lib/analytics';
import Modal from './ui/Modal';

// Opens when a job hits a 402 (quota exceeded). This is the highest-intent
// moment in the product — the user WANTS to clip a video and can't — so it
// sells the subscription first (recurring value: minutes, no watermark,
// permanent clips) and keeps one-time top-ups as a secondary escape hatch.
//
// Conversion techniques used (all honest — no fake scarcity or countdowns):
// - Goal-gradient: copy centers on finishing THIS video, not abstract quota.
// - Compromise effect: all three tiers shown, creator highlighted in the
//   middle — starter floors the price, pro anchors it, creator reads as the
//   sensible pick (and matches the pricing page's "most popular").
// - Outcome framing: every line says what the user GETS (clips ready to post,
//   a library that stays), with the free-plan fact stated second. The earlier
//   copy led with what free costs them, which reads as "pay to undo the
//   restrictions we added" — the losing side of an argument against our own
//   MIT repo, whose headline is literally "no watermarks, no limits".
// - Risk reversal: "cancel anytime" on the CTA.
//
// Deliberately NOT sold here: GPU rendering and the included Gemini key. Both
// are real and both are why the cloud beats self-hosting, but the free plan
// already gets them (the pricing page says "Same GPU rendering" on the free
// tier) — so they belong on the landing/pricing surface facing repo visitors,
// not in a modal shown to someone who is already using them.
const PLAN_BLURBS = {
  starter: 'For getting started',
  creator: 'For daily posting',
  pro: 'For power users',
};

// context: 'wall' (default) = user hit the 402 quota wall mid-task.
//          'upsell' = user opened it voluntarily (results banner, header meter)
//          — different framing: they still HAVE minutes, sell the watermark
//          removal + permanence instead of "you ran out".
export default function TopUpModal({ onClose, required, remaining, context = 'wall' }) {
  const [plans, setPlans] = useState([]);
  const [topups, setTopups] = useState([]);
  const [showTopups, setShowTopups] = useState(false);
  const [busyPrice, setBusyPrice] = useState(null);
  const isUpsell = context === 'upsell';

  useEffect(() => {
    track(isUpsell ? 'UpsellModalSeen' : 'QuotaWallSeen',
          { props: { required: required ?? null, remaining: remaining ?? null } });
    apiJson('/api/billing/plans')
      .then((d) => {
        const monthly = (d.plans || []).filter((p) => p.interval === 'month');
        setPlans(['starter', 'creator', 'pro']
          .map((name) => monthly.find((p) => p.plan === name))
          .filter(Boolean));
        setTopups(d.topups || []);
      })
      .catch(() => {});
    // Plans are fetched once per open; the props only shape the copy.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Instrumented in three steps on purpose. Between 25-jul and 1-ago the modals
  // logged 35 checkout clicks and Stripe recorded ONE new subscription, and
  // nothing in between was measured — this modal fired only its own
  // *ModalCheckout event, so "clicked but never reached Stripe" and "reached
  // Stripe and abandoned" were indistinguishable. CheckoutStarted (click, same
  // meaning as PricingSection's) → CheckoutRedirected (we hold a Stripe URL) →
  // CheckoutFailed (we don't) separates them.
  const source = isUpsell ? 'upsell' : 'wall';

  const buy = async (entry, kind) => {
    setBusyPrice(entry.price_id);
    const props = { kind, plan: entry.plan || null, minutes: entry.minutes, source };
    track(isUpsell ? 'UpsellModalCheckout' : 'QuotaWallCheckout', { props });
    track('CheckoutStarted', { props });
    // Same stash PricingSection sets, so a plan bought from the modal also
    // carries its price into the Subscribed goal (AccountPage reads it back).
    // Top-ups deliberately don't set it — they never count as a subscription.
    if (kind === 'subscription') {
      try {
        localStorage.setItem('os_pending_checkout', JSON.stringify({
          plan: entry.plan, interval: entry.interval, amount: entry.amount,
          currency: entry.currency,
        }));
      } catch (_) { /* ignore storage errors */ }
    }
    try {
      const { url } = await apiJson('/api/billing/checkout', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ price_id: entry.price_id }),
      });
      track('CheckoutRedirected', { props });
      window.location.href = url;
    } catch (e) {
      track('CheckoutFailed', { props: { ...props, reason: String(e?.detail || e?.message || 'unknown').slice(0, 120) } });
      setBusyPrice(null);
      alert(e?.detail || 'Could not start checkout.');
    }
  };

  const fmt = (a, c) => new Intl.NumberFormat('en-US', {
    style: 'currency', currency: (c || 'usd').toUpperCase(), maximumFractionDigits: 0,
  }).format((a || 0) / 100);

  const blockedByLength = typeof required === 'number' && typeof remaining === 'number';

  return (
    <Modal isOpen onClose={onClose} eyebrow="Upgrade"
           title={isUpsell ? 'Keep your clips forever' : 'Your video is ready to clip'} size="xl">
      {/* Goal-gradient framing: they're one step from the thing they came for. */}
      <p className="text-ink2 text-sm mb-6 leading-relaxed max-w-2xl">
        {isUpsell
          ? <>Every clip comes out <b className="text-ink font-medium">ready to post</b> and stays in your
              library for good. On the free plan they carry a watermark and are deleted after 7 days.</>
          : blockedByLength
            ? <>This video needs <b className="text-ink font-medium">{required} min</b> and you have{' '}
                <b className="text-ink font-medium">{Math.max(0, Math.round((remaining || 0) * 10) / 10)} min</b> left
                this month. Pick a plan and it starts rendering right away.</>
            : <>You've used your free minutes for this month. Pick a plan and keep clipping right away.</>}
      </p>

      <ul className="grid sm:grid-cols-3 gap-4 pt-2">
        {plans.map((entry) => {
          const highlight = entry.plan === 'creator';
          const isBusy = busyPrice === entry.price_id;
          return (
            <li key={entry.price_id}
                className={`relative p-5 flex flex-col ${highlight ? 'card-print' : 'card'}`}>
              {highlight && (
                <span className="absolute -top-2.5 left-5 badge-ink">
                  Most popular
                </span>
              )}
              <h3 className="font-display text-lg text-ink capitalize">{entry.plan}</h3>
              <p className="text-muted text-xs mt-0.5">{PLAN_BLURBS[entry.plan] || ''}</p>
              <p className="my-4 flex items-baseline gap-1.5">
                <span className="font-quote text-4xl text-ink tabular-nums leading-none">{fmt(entry.amount, entry.currency)}</span>
                <span className="readout">/mo</span>
              </p>
              <ul className="space-y-2 text-sm text-ink2 mb-5 flex-1 border-t border-rule pt-4">
                <li className="flex items-start gap-2">
                  <Check size={15} className="text-muted shrink-0 mt-0.5" aria-hidden="true" />
                  <span><b className="text-ink font-medium">{entry.minutes} min</b> every month ({Math.round(entry.minutes / 20)}× your free quota)</span>
                </li>
                <li className="flex items-start gap-2">
                  <Check size={15} className="text-muted shrink-0 mt-0.5" aria-hidden="true" />
                  <span>Clips <b className="text-ink font-medium">ready to post</b>, with no watermark</span>
                </li>
                <li className="flex items-start gap-2">
                  <Check size={15} className="text-muted shrink-0 mt-0.5" aria-hidden="true" />
                  <span>Your library <b className="text-ink font-medium">stays</b> (free clips delete after 7 days)</span>
                </li>
                <li className="flex items-start gap-2">
                  <Zap size={15} className="text-ink shrink-0 mt-0.5" aria-hidden="true" />
                  <span>Skips the free queue</span>
                </li>
              </ul>
              <button type="button" onClick={() => buy(entry, 'subscription')} disabled={busyPrice !== null}
                      aria-busy={isBusy || undefined}
                      className={`w-full ${highlight ? 'btn-accent' : 'btn-ghost'}`}>
                {isBusy
                  ? <><Loader2 size={18} className="animate-spin" aria-hidden="true" /><span className="sr-only">Opening checkout…</span></>
                  : `Get ${entry.plan}`}
              </button>
              <p className="text-center text-xs text-muted mt-2.5">Cancel anytime.</p>
            </li>
          );
        })}
        {plans.length === 0 && (
          <li role="status" className="sm:col-span-3 flex justify-center py-8">
            <Loader2 className="animate-spin text-muted" aria-hidden="true" />
            <span className="sr-only">Loading plans…</span>
          </li>
        )}
      </ul>

      {/* Secondary escape hatch: one-time packs, deliberately de-emphasized. */}
      <div className="mt-5 pt-4 border-t border-rule text-center">
        {!showTopups ? (
          <button type="button" onClick={() => setShowTopups(true)}
                  className="min-h-[44px] text-sm text-muted underline decoration-ink/30 underline-offset-2 hover:text-ink hover:decoration-current transition-colors">
            Just need a few extra minutes? One-time packs
          </button>
        ) : (
          <ul className="grid grid-cols-2 gap-3 mt-1 text-left">
            {topups.map((t) => (
              <li key={t.price_id}>
                <button type="button" onClick={() => buy(t, 'topup')} disabled={busyPrice !== null}
                        aria-busy={busyPrice === t.price_id || undefined}
                        className="w-full tray card-hover p-3 text-left disabled:opacity-50 disabled:pointer-events-none">
                  <span className="text-ink text-sm font-medium flex items-center gap-1.5">
                    <Clock size={14} className="text-muted" aria-hidden="true" />+{t.minutes} min
                  </span>
                  <span className="block readout mt-1">{fmt(t.amount, t.currency)} · one-time</span>
                </button>
              </li>
            ))}
            {topups.length === 0 && (
              <li role="status" className="col-span-2 flex justify-center py-3">
                <Loader2 className="animate-spin text-muted" size={18} aria-hidden="true" />
                <span className="sr-only">Loading packs…</span>
              </li>
            )}
          </ul>
        )}
      </div>
    </Modal>
  );
}
