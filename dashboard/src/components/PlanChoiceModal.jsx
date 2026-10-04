import React, { useState, useEffect } from 'react';
import { Check, Loader2, Zap, ArrowRight } from 'lucide-react';
import { apiJson } from '../lib/api';
import Modal from './ui/Modal';

const PLAN_ORDER = ['starter', 'creator', 'pro'];
const FREE_MINUTES = 20;
const fmt = (a, c) => new Intl.NumberFormat('en-US', { style: 'currency', currency: (c || 'usd').toUpperCase(), maximumFractionDigits: 0 }).format((a || 0) / 100);

// Welcome popup after sign-up, instead of dumping the user on the pricing page.
// Free is the default (any Google or permanent-email account qualifies), paid
// plans check out inline.
export default function PlanChoiceModal({ onClose }) {
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    apiJson('/api/billing/plans')
      .then((d) => setPlans(d.plans || []))
      .catch(() => setPlans([]))
      .finally(() => setLoading(false));
  }, []);

  const byPlan = (p) => plans.find((x) => x.plan === p && x.interval === 'month');

  const checkout = async (price_id) => {
    setBusy(price_id);
    try {
      const { url } = await apiJson('/api/billing/checkout', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ price_id }),
      });
      window.location.href = url;
    } catch (e) { setBusy(null); alert(e?.detail || 'Could not start checkout. Please try again.'); }
  };

  const startFree = () => {
    // A signed-in user with a valid account is already on Free — just start.
    onClose();
  };

  return (
    <Modal isOpen onClose={onClose} eyebrow="Welcome" title="Pick how you want to start" size="lg">
      {loading ? (
        <div role="status" className="flex justify-center py-10">
          <Loader2 className="animate-spin text-muted" aria-hidden="true" />
          <span className="sr-only">Loading plans…</span>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 gap-4">
          {/* Free — the default */}
          <section aria-labelledby="plan-choice-free" className="card-print p-5 flex flex-col">
            <p className="readout mb-2">Default</p>
            <div className="flex items-baseline justify-between gap-3">
              <h3 id="plan-choice-free" className="font-display text-xl text-ink">Free</h3>
              <span className="font-quote text-3xl text-ink leading-none">$0</span>
            </div>
            <p className="text-muted text-sm mt-1 mb-4">Try it on your own videos</p>
            <ul className="space-y-2 text-sm text-ink2 mb-5 flex-1 border-t border-rule pt-4">
              <li className="flex items-start gap-2"><Check size={15} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span><b className="text-ink font-medium">{FREE_MINUTES} min</b> / month</span></li>
              <li className="flex items-start gap-2"><Check size={15} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span>No credit card</span></li>
              <li className="flex items-start gap-2 text-muted"><Check size={15} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span>Watermark · clips kept 7 days</span></li>
            </ul>
            <button type="button" onClick={startFree} className="w-full btn-accent">
              Start free <ArrowRight size={15} aria-hidden="true" />
            </button>
            <p className="text-center text-xs text-muted mt-2.5">No card · start clipping now</p>
          </section>

          {/* Paid — compact list */}
          <section aria-labelledby="plan-choice-paid" className="card p-5 flex flex-col">
            <p className="readout mb-2">Upgrade</p>
            <div className="flex items-center justify-between gap-3">
              <h3 id="plan-choice-paid" className="font-display text-xl text-ink">Paid plans</h3>
              <Zap size={16} className="text-muted" aria-hidden="true" />
            </div>
            <p className="text-muted text-sm mt-1 mb-4">No watermark · more minutes · durable library</p>
            <ul className="space-y-2 flex-1">
              {PLAN_ORDER.map((p) => {
                const e = byPlan(p);
                if (!e) return null;
                return (
                  <li key={p}>
                    <button type="button" onClick={() => checkout(e.price_id)} disabled={busy === e.price_id}
                      aria-busy={busy === e.price_id || undefined}
                      className="w-full min-h-[44px] flex items-center justify-between gap-3 border border-rule hover:border-rule2 hover:bg-paper3 rounded-input px-3 py-2 text-left transition-colors disabled:opacity-50">
                      <span className="text-sm text-ink"><span className="capitalize">{p}</span> <span className="text-muted">· {e.minutes} min</span></span>
                      <span className="readout">{busy === e.price_id ? '…' : `${fmt(e.amount, e.currency)}/mo`}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <button type="button" onClick={() => { onClose(); window.location.hash = '#/pricing'; }}
              className="mt-3 min-h-[44px] inline-flex items-center justify-center gap-1.5 text-sm text-muted hover:text-ink transition-colors">
              See full pricing and yearly plans <ArrowRight size={14} aria-hidden="true" />
            </button>
          </section>
        </div>
      )}
    </Modal>
  );
}
