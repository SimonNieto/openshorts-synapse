import React from 'react';
import { Zap } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

// Compact minutes-remaining meter for the header (managed users only).
export default function UsageMeter({ onClick }) {
  const { isManaged, minutes } = useAuth();
  if (!isManaged || !minutes) return null;

  const remaining = Math.round((minutes.remaining || 0) * 10) / 10;
  const allowance = (minutes.plan_allowance || 0) + (minutes.topup_remaining || 0) + (minutes.plan_used || 0);
  const pct = allowance > 0 ? Math.max(4, Math.min(100, (remaining / allowance) * 100)) : 0;
  const low = remaining <= (allowance * 0.2);

  return (
    <button
      type="button"
      onClick={onClick}
      title="Manage your plan"
      aria-label={`${remaining} minutes left${low ? ', running low' : ''}. Manage your plan`}
      className={`status-pill gap-2 hover:bg-paper3 [@media(pointer:coarse)]:min-h-[44px] transition-colors ${low ? 'status-pill-warn' : 'text-ink2 hover:text-ink'}`}
    >
      <Zap size={14} aria-hidden="true" className={low ? 'text-warn' : 'text-muted'} />
      <span aria-hidden="true" className="tabular-nums">{remaining} min</span>
      <span aria-hidden="true" className="w-12 h-1 rounded-full bg-[color:var(--color-rule-2)] overflow-hidden hidden sm:inline-block">
        <span className={`block h-full rounded-full ${low ? 'bg-warn' : 'bg-ink2'}`} style={{ width: `${pct}%` }} />
      </span>
    </button>
  );
}
