import React, { useState, useEffect } from 'react';
import { FileText, ExternalLink, Download, Loader2 } from 'lucide-react';
import { apiJson } from '../lib/api';

// Legally valid invoices for the account's Stripe charges, issued by
// AgentLedger. The backend hands us pre-signed public links, so "View" and
// "Download" open directly without any extra auth from the browser.
const STATUS_CLASS = {
  paid: 'badge-ok',
  partially_paid: 'badge-warn',
  overdue: 'badge-warn',
};

function formatDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return y && m && d ? `${d}/${m}/${y}` : iso;
}

function formatMoney(amount, currency) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return `${amount} ${currency}`;
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: (currency || 'EUR').toUpperCase() }).format(n);
  } catch (_) {
    return `${n.toFixed(2)} ${currency}`;
  }
}

export default function InvoicesCard() {
  const [invoices, setInvoices] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    apiJson('/api/billing/invoices')
      .then((d) => { if (!cancelled) setInvoices(Array.isArray(d.invoices) ? d.invoices : []); })
      .catch((e) => { if (!cancelled) { setError(e?.detail || 'Could not load invoices.'); setInvoices([]); } });
    return () => { cancelled = true; };
  }, []);

  return (
    <section aria-labelledby="invoices-title" className="card p-5 sm:p-6">
      <h3 id="invoices-title" className="font-display text-lg text-ink mb-1 flex items-center gap-2">
        <FileText size={16} className="text-muted" aria-hidden="true" /> Invoices
      </h3>
      <p className="text-muted text-sm mb-4">
        Legally valid invoices for every charge on this account.
      </p>

      {invoices === null ? (
        <div role="status" className="flex items-center gap-2 text-muted text-sm py-4">
          <Loader2 size={16} className="animate-spin" aria-hidden="true" /> Loading invoices…
        </div>
      ) : error ? (
        <p role="alert" className="text-sm text-warn">{error}</p>
      ) : invoices.length === 0 ? (
        <p className="tray px-4 py-3 text-sm text-muted leading-relaxed">
          No invoices yet. They appear here after your first payment — give it a few minutes if you just subscribed.
        </p>
      ) : (
        <ul className="divide-y divide-rule border-y border-rule">
          {invoices.map((inv) => (
            <li key={inv.doc_number || inv.public_url} className="py-3 flex items-center justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <div className="text-ink font-medium font-mono text-xs break-all">{inv.doc_number}</div>
                <div className="text-muted text-xs mt-1 flex items-center flex-wrap gap-x-2 gap-y-1">
                  <time dateTime={inv.doc_date || undefined}>{formatDate(inv.doc_date)}</time>
                  <span aria-hidden="true">·</span>
                  <span className="text-ink2 tabular-nums">{formatMoney(inv.total, inv.currency)}</span>
                  {inv.status && (
                    <span className={STATUS_CLASS[inv.status] || 'badge-warn'}>{inv.status.replace(/_/g, ' ')}</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {inv.public_url && (
                  <a href={inv.public_url} target="_blank" rel="noopener noreferrer" className="btn-ghost px-3 py-1.5 text-xs"
                     aria-label={inv.doc_number ? `View invoice ${inv.doc_number}` : 'View invoice'}>
                    <ExternalLink size={14} aria-hidden="true" /> View
                  </a>
                )}
                {inv.pdf_url && (
                  <a href={inv.pdf_url} target="_blank" rel="noopener noreferrer" className="btn-ghost px-3 py-1.5 text-xs"
                     aria-label={inv.doc_number ? `Download invoice ${inv.doc_number} as PDF` : 'Download invoice as PDF'}>
                    <Download size={14} aria-hidden="true" /> PDF
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
