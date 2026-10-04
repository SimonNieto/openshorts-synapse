import React, { useState, useEffect } from 'react';
import { Check, Loader2, Zap, Cpu, KeyRound, Send, HardDrive, Bot } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { apiJson } from '../lib/api';
import { track } from '../lib/analytics';
import SegmentedControl from './ui/SegmentedControl';

const PLAN_ORDER = ['starter', 'creator', 'pro'];
const PLAN_BLURB = {
  starter: 'For getting started',
  creator: 'For regular creators',
  pro: 'For power users & teams',
};
const HIGHLIGHT = 'creator';
const FREE_MINUTES = 20;


const fmt = (amount, currency) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: (currency || 'usd').toUpperCase(), maximumFractionDigits: 0 }).format((amount || 0) / 100);

// Free tier + 3 paid tiers with monthly/annual toggle. Checkout requires sign-in.
export default function PricingSection({ onRequireLogin }) {
  const { isSignedIn } = useAuth();
  const [plans, setPlans] = useState([]);
  const [interval, setInterval] = useState('month');
  const [loading, setLoading] = useState(true);
  const [busyPrice, setBusyPrice] = useState(null);

  useEffect(() => {
    apiJson('/api/billing/plans')
      .then((d) => setPlans(d.plans || []))
      .catch(() => setPlans([]))
      .finally(() => setLoading(false));
  }, []);

  const checkout = async (entry) => {
    if (!isSignedIn) { onRequireLogin?.(entry.price_id); return; }
    setBusyPrice(entry.price_id);
    // `source` segments this surface from the two modals (see TopUpModal), which
    // now emit the same three events.
    const props = { plan: entry.plan, interval: entry.interval, source: 'pricing' };
    track('CheckoutStarted', { props });
    // Stash the price so we can attach real revenue to the Subscribed goal when
    // the user returns from Stripe (see AccountPage's checkout=success handler).
    try {
      localStorage.setItem('os_pending_checkout', JSON.stringify({
        plan: entry.plan, interval: entry.interval, amount: entry.amount, currency: entry.currency,
      }));
    } catch (_) { /* ignore storage errors */ }
    try {
      const { url } = await apiJson('/api/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ price_id: entry.price_id }),
      });
      track('CheckoutRedirected', { props });
      window.location.href = url;
    } catch (e) {
      track('CheckoutFailed', { props: { ...props, reason: String(e?.detail || e?.message || 'unknown').slice(0, 120) } });
      setBusyPrice(null);
      alert(e?.detail || 'Could not start checkout. Please try again.');
    }
  };

  if (loading) {
    return (
      <div role="status" aria-live="polite" className="flex justify-center py-16">
        <Loader2 className="animate-spin text-muted" aria-hidden="true" />
        <span className="sr-only">Loading plans…</span>
      </div>
    );
  }

  const byPlan = (plan) => plans.find((p) => p.plan === plan && p.interval === interval);

  return (
    <div className="max-w-6xl mx-auto">
      <fieldset className="max-w-xs mx-auto mb-12">
        <legend className="sr-only">Billing period</legend>
        <SegmentedControl
          size="sm"
          value={interval}
          onChange={setInterval}
          options={[
            { value: 'month', label: 'Monthly' },
            { value: 'year', label: 'Yearly', hint: '2 months free' },
          ]}
        />
      </fieldset>

      <ul className="grid md:grid-cols-2 lg:grid-cols-4 gap-5 items-stretch">
        {/* Free tier — no card, Google sign-in only */}
        <li className="relative card p-6 flex flex-col">
          <h3 className="font-display text-lg text-ink">Free</h3>
          <p className="text-muted text-sm mt-1">Try it on your own videos</p>
          <p className="my-6 flex items-baseline gap-1.5">
            <span className="font-quote text-5xl text-ink tabular-nums leading-none">$0</span>
            <span className="readout">/mo</span>
          </p>
          <ul className="space-y-2.5 text-sm text-ink2 mb-6 flex-1 border-t border-rule pt-5">
            <li className="flex items-start gap-2.5"><Check size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span><b className="text-ink font-medium">{FREE_MINUTES} min</b> of video / month</span></li>
            <li className="flex items-start gap-2.5"><Check size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span>YouTube URL or upload</span></li>
            <li className="flex items-start gap-2.5"><Cpu size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span>Same <b className="text-ink font-medium">GPU rendering</b>, about 50s per 8-min video</span></li>
            <li className="flex items-start gap-2.5"><KeyRound size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span>Gemini key included, no setup</span></li>
            <li className="flex items-start gap-2.5"><Check size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span>No credit card — Google sign-in</span></li>
            <li className="flex items-start gap-2.5 text-muted"><Check size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span>Watermark · clips kept 7 days</span></li>
          </ul>
          <button
            type="button"
            onClick={() => { if (!isSignedIn) { onRequireLogin?.(null); } else { window.location.hash = ''; } }}
            className="w-full btn-ghost"
          >
            Start free
          </button>
          <p className="text-center text-xs text-muted mt-2.5">Free minutes reset monthly.</p>
        </li>

        {PLAN_ORDER.map((plan) => {
          const entry = byPlan(plan);
          if (!entry) return null;
          const highlight = plan === HIGHLIGHT;
          const busy = busyPrice === entry.price_id;
          return (
            <li
              key={plan}
              className={`relative p-6 flex flex-col ${highlight ? 'card-print' : 'card'}`}
            >
              {highlight && (
                <span className="absolute -top-2.5 left-6 badge-ink">
                  Most popular
                </span>
              )}
              <h3 className="font-display text-lg text-ink capitalize">{plan}</h3>
              <p className="text-muted text-sm mt-1">{PLAN_BLURB[plan]}</p>
              <p className="my-6 flex items-baseline gap-1.5">
                <span className="font-quote text-5xl text-ink tabular-nums leading-none">{fmt(entry.amount, entry.currency)}</span>
                <span className="readout">/{interval === 'month' ? 'mo' : 'yr'}</span>
              </p>
              <ul className="space-y-2.5 text-sm text-ink2 mb-6 flex-1 border-t border-rule pt-5">
                <li className="flex items-start gap-2.5"><Check size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span><b className="text-ink font-medium">{entry.minutes} min</b> of video / month</span></li>
                <li className="flex items-start gap-2.5"><Check size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span><b className="text-ink font-medium">No watermark</b>, no 7-day clip expiry</span></li>
                <li className="flex items-start gap-2.5"><Cpu size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span><b className="text-ink font-medium">GPU rendering</b>, about 50s per 8-min video</span></li>
                <li className="flex items-start gap-2.5"><KeyRound size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span>Gemini key + auto-posting included</span></li>
                <li className="flex items-start gap-2.5"><Bot size={16} className="text-muted shrink-0 mt-0.5" aria-hidden="true" /> <span><b className="text-ink font-medium">MCP + API access</b> for AI agents &amp; automations</span></li>
                {plan === 'pro' && <li className="flex items-start gap-2.5"><Zap size={16} className="text-ink shrink-0 mt-0.5" aria-hidden="true" /> <span>Priority processing queue</span></li>}
              </ul>
              <button
                type="button"
                onClick={() => checkout(entry)}
                disabled={busy}
                aria-busy={busy || undefined}
                className={`w-full ${highlight ? 'btn-accent' : 'btn-ghost'}`}
              >
                {busy
                  ? <><Loader2 size={18} className="animate-spin" aria-hidden="true" /><span className="sr-only">Opening checkout…</span></>
                  : `Get ${plan}`}
              </button>
              <p className="text-center text-xs text-muted mt-2.5">Billed {interval === 'month' ? 'monthly' : 'yearly'}. Cancel anytime.</p>
            </li>
          );
        })}
      </ul>

      {/* What every plan includes vs what's bring-your-own-key */}
      <div className="mt-12 grid md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-5">
        <section className="card p-6" aria-labelledby="plans-included">
          <h3 id="plans-included" className="font-display text-base text-ink mb-4 flex items-center gap-2">
            <Check size={16} className="text-muted" aria-hidden="true" /> Included in every plan
          </h3>
          <ul className="space-y-3 text-sm text-ink2 leading-relaxed">
            <li className="flex items-start gap-2.5"><Cpu size={15} className="text-muted shrink-0 mt-1" aria-hidden="true" /> <span><b className="text-ink font-medium">Our NVIDIA GPU does the rendering.</b> An 8-minute video is clipped in about 50 seconds, instead of the 5 to 8 minutes it takes on a typical CPU.</span></li>
            <li className="flex items-start gap-2.5"><KeyRound size={15} className="text-muted shrink-0 mt-1" aria-hidden="true" /> <span><b className="text-ink font-medium">The Gemini API key is included.</b> Nothing to sign up for, nothing to paste, no per-request quota of your own to babysit.</span></li>
            <li className="flex items-start gap-2.5"><Send size={15} className="text-muted shrink-0 mt-1" aria-hidden="true" /> <span><b className="text-ink font-medium">Auto-posting is already wired up</b> for TikTok, Instagram Reels and YouTube Shorts.</span></li>
            <li className="flex items-start gap-2.5"><HardDrive size={15} className="text-muted shrink-0 mt-1" aria-hidden="true" /> <span><b className="text-ink font-medium">Clips are stored and served for you</b>, ready to re-open and re-edit from any browser.</span></li>
            <li className="flex items-start gap-2.5"><Check size={15} className="text-muted shrink-0 mt-1" aria-hidden="true" /> <span>Full <b className="text-ink font-medium">YouTube Studio</b>: titles, thumbnails and descriptions.</span></li>
            <li className="flex items-start gap-2.5"><Bot size={15} className="text-muted shrink-0 mt-1" aria-hidden="true" /> <span><b className="text-ink font-medium">MCP server &amp; API for agents.</b> Connect Claude, ChatGPT or n8n to an always-on endpoint and automate clipping end to end. API calls use the same minutes, nothing extra to buy. <a href="/mcp" className="text-ink underline decoration-ink/30 underline-offset-2 hover:decoration-current" target="_blank" rel="noopener">Guide</a>.</span></li>
          </ul>
          <p className="text-xs text-muted mt-4 pt-4 border-t border-rule leading-relaxed">
            Your monthly minutes cover video processing. Titles &amp; descriptions are free;
            AI <b className="text-ink2 font-medium">thumbnail image generation</b> uses ~3 min of your quota per batch.
          </p>
        </section>
        <section className="tray p-6" aria-labelledby="plans-byok">
          <h3 id="plans-byok" className="font-display text-base text-ink mb-4 flex items-center gap-2">
            <Zap size={16} className="text-muted" aria-hidden="true" /> Bring your own key
          </h3>
          <p className="text-sm text-ink2 mb-3 leading-relaxed">
            <b className="text-ink font-medium">AI Shorts</b> (AI-actor UGC videos) and <b className="text-ink font-medium">voice dubbing</b> use premium generation from
            <b className="text-ink font-medium"> fal.ai</b> and <b className="text-ink font-medium">ElevenLabs</b>. Connect your own keys for those — you're billed by those
            providers directly (typically ~$0.65-2 per video). Your plan still covers the script &amp; orchestration.
          </p>
          <p className="text-xs text-muted">Managed credits for these are coming later — no keys needed.</p>
        </section>
      </div>

      <p className="text-center text-muted text-sm mt-10">
        Start free right here, upgrade for more minutes and no watermark, or run it yourself on your own hardware.
      </p>
    </div>
  );
}
