import React, { useState, useCallback } from 'react';
import { Plug, Copy, Check } from 'lucide-react';
import { getApiUrl } from '../config';
import SegmentedControl from './ui/SegmentedControl';

// "Connect an agent": the one place that tells a person how to drive
// OpenShorts from Claude, ChatGPT, Cursor or n8n. Cloud accounts connect by
// URL (claude.ai and ChatGPT run the OAuth flow themselves; CLI clients take
// an API key); a self-hosted install has no auth, so every snippet is the
// local URL and nothing else.

const CLOUD_MCP_URL = 'https://mcp.openshorts.app/mcp';

// The self-hosted dashboard proxies /api and /videos to the backend but not
// /mcp (neither the Vite dev proxy nor nginx.conf), so an MCP client must
// talk to the API container itself: VITE_API_URL when it is set, otherwise
// the backend's default port on the same host.
function localMcpUrl() {
  const u = getApiUrl('/mcp');
  if (u.startsWith('http')) return u;
  try { return `${window.location.protocol}//${window.location.hostname}:8000/mcp`; } catch { return 'http://localhost:8000/mcp'; }
}

function buildClients({ cloud, url }) {
  const key = cloud ? 'osk_YOUR_KEY' : null;
  const header = key ? ` \\\n  --header "Authorization: Bearer ${key}"` : '';
  const desktopArgs = key
    ? `["-y", "mcp-remote", "${url}", "--header", "Authorization: Bearer ${key}"]`
    : `["-y", "mcp-remote", "${url}"]`;
  const cursorHeaders = key ? `,\n      "headers": { "Authorization": "Bearer ${key}" }` : '';
  return [
    cloud && {
      id: 'claude-ai', label: 'Claude (claude.ai)', kind: 'steps',
      steps: [
        'Open claude.ai → Settings → Connectors → Add custom connector.',
        `Paste this URL and save: ${url}`,
        'Click Connect: you will land on Synapse AI to approve the access, then the 8 tools appear in every chat.',
      ],
      snippet: url,
    },
    cloud && {
      id: 'chatgpt', label: 'ChatGPT', kind: 'steps',
      steps: [
        'Open ChatGPT → Settings → Connectors → Create (developer mode).',
        `Name it Synapse AI, paste this MCP server URL, choose OAuth: ${url}`,
        'Approve the access on Synapse AI when asked. Done: ask ChatGPT to clip a video.',
      ],
      snippet: url,
    },
    {
      id: 'claude-code', label: 'Claude Code', kind: 'code', lang: 'bash',
      snippet: `claude mcp add --transport http openshorts ${url}${header}`,
      note: cloud ? 'Create a key below and paste it in place of osk_YOUR_KEY.' : 'No key needed on a self-hosted install.',
    },
    {
      id: 'claude-desktop', label: 'Claude Desktop', kind: 'code', lang: 'json',
      snippet: `{\n  "mcpServers": {\n    "openshorts": {\n      "command": "npx",\n      "args": ${desktopArgs}\n    }\n  }\n}`,
      note: 'Settings → Developer → Edit config (claude_desktop_config.json), then restart Claude.',
    },
    {
      id: 'cursor', label: 'Cursor', kind: 'code', lang: 'json',
      snippet: `{\n  "mcpServers": {\n    "openshorts": {\n      "url": "${url}"${cursorHeaders}\n    }\n  }\n}`,
      note: 'Settings → MCP → Add new global MCP server (.cursor/mcp.json).',
    },
    {
      id: 'n8n', label: 'n8n', kind: 'steps',
      steps: [
        'Add an "MCP Client Tool" node to your AI Agent.',
        `Endpoint: ${url}  ·  Transport: HTTP Streamable.`,
        cloud ? 'Authentication: Bearer, with a key from below.' : 'Authentication: none.',
      ],
      snippet: url,
    },
    {
      id: 'curl', label: 'curl', kind: 'code', lang: 'bash',
      snippet: `curl -X POST ${url} \\\n  -H "Content-Type: application/json"${key ? ` \\\n  -H "Authorization: Bearer ${key}"` : ''} \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`,
      note: 'Plain JSON-RPC over HTTP: the same endpoint every client above talks to.',
    },
  ].filter(Boolean);
}

export default function McpConnectCard({ cloud = true, compact = false }) {
  const url = cloud ? CLOUD_MCP_URL : localMcpUrl();
  const clients = buildClients({ cloud, url });
  const [active, setActive] = useState(clients[0].id);
  const [copied, setCopied] = useState(false);
  const current = clients.find((c) => c.id === active) || clients[0];

  const copy = useCallback(() => {
    navigator.clipboard?.writeText(current.snippet).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }).catch(() => {});
  }, [current]);

  return (
    <section aria-labelledby="connect-agent-title" className="card p-5 sm:p-6" id="connect-agent">
      <h3 id="connect-agent-title" className="font-display text-lg text-ink mb-1 flex items-center gap-2">
        <Plug size={16} className="text-muted" aria-hidden="true" /> Connect an agent
      </h3>
      <p className="text-muted text-sm mb-5 leading-relaxed">
        Let Claude, ChatGPT, Cursor or n8n clip and publish for you through the built-in MCP server:
        8 tools (process a video or upload one, check a job, list clips, add subtitles, recut, publish, quota).
        {cloud
          ? ' claude.ai and ChatGPT connect with one URL and a sign-in; CLI clients use an API key.'
          : ' This install runs without accounts, so no key is needed.'}
      </p>

      <fieldset className="mb-4">
        <legend className="readout mb-2">Client</legend>
        <SegmentedControl
          size="sm"
          columns={4}
          value={active}
          onChange={(id) => { setActive(id); setCopied(false); }}
          options={clients.map((c) => ({ value: c.id, label: c.label }))}
        />
      </fieldset>

      {current.kind === 'steps' && (
        <ol className="list-decimal marker:text-muted pl-5 space-y-1.5 text-sm text-ink2 mb-3 break-words">
          {current.steps.map((s) => <li key={s}>{s}</li>)}
        </ol>
      )}

      <div className="relative">
        <pre className={`font-mono text-ink2 whitespace-pre-wrap break-all rounded-input border border-rule bg-paper p-3 pr-24 text-xs ${compact ? '' : 'leading-relaxed'}`}>
          {current.snippet}
        </pre>
        <button type="button" onClick={copy} className="btn-ghost absolute top-2 right-2 px-2.5 py-1 text-xs bg-paper2">
          {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />} {copied ? 'Copied' : 'Copy'}
        </button>
        <span className="sr-only" aria-live="polite">{copied ? 'Copied to the clipboard' : ''}</span>
      </div>
      {current.note && <p className="text-muted text-xs mt-2.5 leading-relaxed">{current.note}</p>}
    </section>
  );
}
