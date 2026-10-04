import React, { useState, useEffect, useCallback } from 'react';
import { KeyRound, Plus, Trash2, Copy, Check, Loader2 } from 'lucide-react';
import { apiJson } from '../lib/api';

// API keys for programmatic access (MCP clients, scripts, n8n). The raw key is
// returned exactly once by POST /api/keys, so it is surfaced in a one-time
// banner the user must copy before it disappears.
export default function ApiKeysCard() {
  const [keys, setKeys] = useState(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [freshKey, setFreshKey] = useState(null); // { key, name } shown once
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    apiJson('/api/keys').then((d) => setKeys(d.keys || [])).catch(() => setKeys([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const createKey = useCallback(async () => {
    setBusy(true);
    try {
      const d = await apiJson('/api/keys', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() || undefined }),
      });
      setFreshKey(d);
      setCopied(false);
      setName('');
      load();
    } catch (e) { alert(e?.detail || 'Could not create the key.'); }
    setBusy(false);
  }, [name, load]);

  const revoke = useCallback(async (k) => {
    if (!window.confirm(`Revoke "${k.name}"? Anything using it stops working immediately.`)) return;
    try {
      await apiJson(`/api/keys/${k.id}`, { method: 'DELETE' });
      load();
    } catch (e) { alert(e?.detail || 'Could not revoke the key.'); }
  }, [load]);

  const copyKey = useCallback(() => {
    navigator.clipboard?.writeText(freshKey.key).then(() => setCopied(true)).catch(() => {});
  }, [freshKey]);

  const active = (keys || []).filter((k) => !k.revoked);

  return (
    <section aria-labelledby="api-keys-title" className="card p-5 sm:p-6">
      <h3 id="api-keys-title" className="font-display text-lg text-ink mb-1 flex items-center gap-2">
        <KeyRound size={16} className="text-muted" aria-hidden="true" /> API keys
      </h3>
      <p className="text-muted text-sm mb-5 leading-relaxed">
        Keys for CLI clients, scripts and the REST API (see &ldquo;Connect an agent&rdquo; above).
        Apps connected through claude.ai or ChatGPT show up here too: revoking a key disconnects
        that app. Keys use your plan&apos;s minutes.
      </p>

      {freshKey && (
        <div role="status" aria-live="polite" className="mb-5 rounded-card border border-rule2 bg-paper3 p-4 text-sm">
          <p className="text-ink mb-3">
            <b className="font-semibold">Copy your new key now.</b> For security it will never be shown again.
          </p>
          <div className="flex flex-col sm:flex-row sm:items-center gap-2">
            <code className="font-mono text-xs text-ink bg-paper border border-rule rounded-input px-3 py-2 flex-1 break-all select-all">{freshKey.key}</code>
            <button type="button" onClick={copyKey} className="btn-ghost px-3 py-1.5 shrink-0">
              {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />} {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}

      {keys === null ? (
        <div role="status" className="flex justify-center py-4">
          <Loader2 className="animate-spin text-muted" size={18} aria-hidden="true" />
          <span className="sr-only">Loading keys…</span>
        </div>
      ) : (
        <>
          {active.length > 0 && (
            <ul className="divide-y divide-rule border-y border-rule mb-5">
              {active.map((k) => (
                <li key={k.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                  <div className="min-w-0">
                    <span className="text-ink break-all">{k.name}</span>{' '}
                    <code className="readout normal-case">{k.prefix}…</code>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-muted text-xs">
                      {k.last_used_at ? `Used ${new Date(k.last_used_at).toLocaleDateString()}` : 'Never used'}
                    </span>
                    <button type="button" onClick={() => revoke(k)} title="Revoke key" aria-label={`Revoke key ${k.name}`}
                            className="p-2.5 -mr-2 rounded-input text-muted hover:text-danger hover:bg-paper3 transition-colors">
                      <Trash2 size={15} aria-hidden="true" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-col sm:flex-row gap-2">
            <label htmlFor="api-key-name" className="sr-only">Key name</label>
            <input
              id="api-key-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') createKey(); }}
              placeholder="Key name (e.g. n8n, claude)"
              className="input-field flex-1 text-sm"
              maxLength={60}
            />
            <button type="button" onClick={createKey} disabled={busy} aria-busy={busy || undefined} className="btn-ghost px-4 py-2 shrink-0">
              {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />} Create key
            </button>
          </div>
        </>
      )}
    </section>
  );
}
