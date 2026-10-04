import React, { useEffect, useState } from 'react';
import { Loader2, Compass, ExternalLink, AlertCircle, CheckCircle2, AlertTriangle, XCircle, RefreshCw } from 'lucide-react';
import { apiJson } from '../lib/api';

const MINE_KEY = 'synapse_my_channel';

function formatCount(n) {
    if (n == null) return '–';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, '')}K`;
    return String(n);
}

// The three colours (design.md: ok / warn / danger are real states, always with an icon and a word).
const TONE = {
    green: { cls: 'border-ok/40 bg-ok/10 text-ok', Icon: CheckCircle2 },
    orange: { cls: 'border-warn/40 bg-warn/10 text-warn', Icon: AlertTriangle },
    red: { cls: 'border-danger/40 bg-danger/10 text-danger', Icon: XCircle },
};
const WORDS = {
    overall: { green: 'Good for you', orange: 'Check first', red: 'Not for you' },
    rights: { green: 'Clip and monetise: yes', orange: 'Clip and monetise: unclear', red: 'Clip and monetise: no' },
    fit: { green: 'Fits your niche', orange: 'Partly fits', red: 'Off your niche' },
};
const BASIS = {
    'said by the channel': 'The channel says so',
    'known reputation': 'Known reputation, not verified',
    'nothing found': 'Nothing found on the channel',
};

function Badge({ color, kind, big }) {
    const t = TONE[color] || TONE.orange;
    return (
        <span className={`inline-flex items-center gap-1.5 rounded-input border ${t.cls} ${big ? 'px-2.5 py-1 text-sm' : 'px-2 py-0.5 text-xs'} font-medium whitespace-nowrap`}>
            <t.Icon size={big ? 15 : 13} aria-hidden="true" />
            {WORDS[kind][color] || WORDS[kind].orange}
        </span>
    );
}

function ChannelCard({ c }) {
    return (
        <li className="p-4 sm:p-5 space-y-3">
            <div className="flex items-start gap-3">
                {c.avatar
                    ? <img src={c.avatar} alt="" className="w-11 h-11 rounded-full border border-rule2 shrink-0" loading="lazy" />
                    : <span className="w-11 h-11 rounded-full bg-paper3 shrink-0" aria-hidden="true" />}
                <div className="min-w-0 flex-1">
                    <a href={c.url} target="_blank" rel="noopener noreferrer"
                        className="group inline-flex items-center gap-1.5 text-[15px] font-medium text-ink hover:underline underline-offset-2">
                        {c.title}
                        <ExternalLink size={12} className="text-muted" aria-hidden="true" />
                        <span className="sr-only">(opens YouTube in a new tab)</span>
                    </a>
                    <p className="readout mt-1 normal-case">
                        {c.handle && <span>{c.handle} · </span>}
                        {formatCount(c.subscribers)} subscribers · {formatCount(c.median_views)} views per video
                        {c.per_week != null && <> · {c.per_week} a week</>}
                        {c.long_share != null && <> · {Math.round(c.long_share * 100)}% long</>}
                    </p>
                </div>
                <Badge color={c.overall} kind="overall" big />
            </div>
            {c.summary && <p className="text-sm text-ink2 leading-relaxed">{c.summary}</p>}
            <dl className="grid gap-3 sm:grid-cols-2">
                <div className="tray px-3 py-2.5 space-y-1.5">
                    <dt><Badge color={c.rights} kind="rights" /></dt>
                    <dd className="text-xs text-ink2 leading-relaxed">
                        {c.rights_why}
                        <span className="block text-muted mt-1">{BASIS[c.rights_basis] || c.rights_basis}</span>
                        {c.rights_basis === 'said by the channel' && c.evidence?.slice(0, 2).map((e) => (
                            <q key={e.quote} className="block text-muted italic mt-1 break-words">{e.quote}</q>
                        ))}
                    </dd>
                </div>
                <div className="tray px-3 py-2.5 space-y-1.5">
                    <dt><Badge color={c.fit} kind="fit" /></dt>
                    <dd className="text-xs text-ink2 leading-relaxed">{c.fit_why}</dd>
                </div>
            </dl>
        </li>
    );
}

/**
 * « Niches » (niche_explorer.py): her channel sets her niche; a link (a show such as Joe Rogan) opens the niches
 * running parallel to it. Every show found is rated twice — may she clip and monetise it, does it follow her niche —
 * in green / orange / red. A run is kept on the server: asking the same thing again costs nothing.
 */
export default function NichesTab() {
    const [mine, setMine] = useState(() => { try { return localStorage.getItem(MINE_KEY) || ''; } catch { return ''; } });
    const [link, setLink] = useState('');
    const [result, setResult] = useState(null);
    const [runs, setRuns] = useState([]);
    const [loading, setLoading] = useState(false);
    const [seconds, setSeconds] = useState(0);
    const [error, setError] = useState('');
    const [goodOnly, setGoodOnly] = useState(false);

    const loadRuns = async () => {
        try { setRuns((await apiJson('/api/niches/history')).runs || []); } catch { /* the list is a convenience */ }
    };
    useEffect(() => { loadRuns(); }, []);
    useEffect(() => {
        if (!loading) return undefined;
        setSeconds(0);
        const t = setInterval(() => setSeconds((s) => s + 1), 1000);
        return () => clearInterval(t);
    }, [loading]);

    const run = async (m, l, refresh = false) => {
        if ((!m.trim() && !l.trim()) || loading) return;
        setLoading(true);
        setError('');
        try { localStorage.setItem(MINE_KEY, m.trim()); } catch { /* private mode */ }
        try {
            setResult(await apiJson('/api/niches/explore', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mine: m, link: l, refresh }),
            }));
            loadRuns();
        } catch (e) {
            setError(e.detail || e.message || 'The search failed.');
        } finally {
            setLoading(false);
        }
    };

    const show = (chans) => (goodOnly ? chans.filter((c) => c.overall === 'green') : chans);
    const greens = result ? result.niches.reduce((a, n) => a + n.channels.filter((c) => c.overall === 'green').length, 0) : 0;

    return (
        <div className="space-y-8 animate-fade">
            <header className="max-w-2xl">
                <p className="eyebrow mb-2">Research</p>
                <h2 className="page-title">Find shows to clip</h2>
                <p className="page-lede mt-3">
                    Your channel sets your niche. Add a link, a show such as Joe Rogan, to open the niches around it.
                    Every show found gets two colours: can you clip and monetise it, and does it follow your niche.
                </p>
            </header>

            <section aria-labelledby="nx-form-heading" className="card-print p-4 sm:p-6">
                <h3 id="nx-form-heading" className="sr-only">What to explore</h3>
                <form onSubmit={(e) => { e.preventDefault(); run(mine, link); }} className="space-y-4">
                    <div className="grid gap-4 md:grid-cols-2">
                        <div>
                            <label htmlFor="nx-mine" className="block text-sm font-medium text-ink mb-2">Your channel</label>
                            <input id="nx-mine" value={mine} onChange={(e) => setMine(e.target.value)} className="input-field"
                                placeholder="https://www.youtube.com/@yourchannel" aria-describedby="nx-mine-hint" />
                            <p id="nx-mine-hint" className="text-xs text-muted mt-1">Your niche, read from your public videos. Kept on this computer.</p>
                        </div>
                        <div>
                            <label htmlFor="nx-link" className="block text-sm font-medium text-ink mb-2">A link to explore</label>
                            <input id="nx-link" value={link} onChange={(e) => setLink(e.target.value)} className="input-field"
                                placeholder="https://www.youtube.com/@joerogan" aria-describedby="nx-link-hint" />
                            <p id="nx-link-hint" className="text-xs text-muted mt-1">A channel, a video or a name. Leave it blank to explore around your channel.</p>
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                        <button type="submit" disabled={(!mine.trim() && !link.trim()) || loading} className="btn-accent">
                            {loading ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Compass size={16} aria-hidden="true" />}
                            {loading ? 'Exploring…' : 'Find the niches'}
                        </button>
                        <p className="readout normal-case" aria-live="polite">
                            {loading ? `Reading YouTube, then the AI rates every show · ${seconds} s (about 1 to 3 min)` : ''}
                        </p>
                    </div>
                    {error && (
                        <div role="alert" className="flex items-start gap-2.5 rounded-input border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink">
                            <AlertCircle size={16} className="text-danger shrink-0 mt-0.5" aria-hidden="true" />
                            <span className="break-words">{error}</span>
                        </div>
                    )}
                    {runs.length > 0 && (
                        <div>
                            <p id="nx-runs" className="text-xs text-muted mb-1.5">Earlier searches, free to reopen</p>
                            <div className="flex flex-wrap gap-1.5" role="group" aria-labelledby="nx-runs">
                                {runs.map((r) => (
                                    <button key={`${r.mine}|${r.link}`} type="button" disabled={loading}
                                        onClick={() => { setMine(r.mine); setLink(r.link); run(r.mine, r.link); }}
                                        className="px-3 py-1.5 [@media(pointer:coarse)]:min-h-[44px] rounded-input border border-rule2 bg-paper2 text-xs text-ink2 hover:border-ink hover:text-ink transition-colors">
                                        {r.link || r.mine} <span className="text-muted">· {r.green} good</span>
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                </form>
            </section>

            {result && (
                <section aria-labelledby="nx-results-heading" className="space-y-6">
                    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-rule2 pb-4">
                        <div className="max-w-3xl">
                            <p className="readout mb-1">Your niche</p>
                            <h3 id="nx-results-heading" className="font-display text-xl text-ink">{result.niche.niche}</h3>
                            <p className="text-sm text-ink2 mt-2 leading-relaxed">{result.niche.summary}</p>
                            <p className="text-xs text-muted mt-2 leading-relaxed">A good show to clip for you: {result.niche.good_source}</p>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                            <p className="readout normal-case">{greens} good · {result.cached ? 'kept from an earlier search' : 'fresh'}</p>
                            <div className="flex gap-2">
                                <button type="button" aria-pressed={goodOnly} onClick={() => setGoodOnly(!goodOnly)}
                                    className={`btn-ghost px-3 py-1.5 text-xs ${goodOnly ? 'border-ink text-ink' : ''}`}>
                                    {goodOnly ? 'Show all' : 'Good only'}
                                </button>
                                <button type="button" disabled={loading} onClick={() => run(result.asked.mine, result.asked.link, true)}
                                    className="btn-ghost px-3 py-1.5 text-xs">
                                    <RefreshCw size={13} aria-hidden="true" /> Search again
                                </button>
                            </div>
                        </div>
                    </div>

                    <p className="text-xs text-muted leading-relaxed max-w-3xl">
                        Green for clipping only when the channel itself says clips are welcome (quoted below) or its
                        reputation is well known; orange when nothing says either way. A lead, not a licence: check before you monetise.
                    </p>

                    {result.link && (
                        <div>
                            <p className="readout mb-2">The link</p>
                            <ul className="card overflow-hidden"><ChannelCard c={result.link} /></ul>
                        </div>
                    )}

                    {result.niches.map((n) => (
                        <div key={n.name} className="space-y-3">
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                                <h4 className="font-display text-lg text-ink">{n.name}</h4>
                                <Badge color={n.fit} kind="fit" />
                            </div>
                            <p className="text-xs text-muted leading-relaxed max-w-3xl">{n.why}</p>
                            {show(n.channels).length > 0 ? (
                                <ul className="card divide-y divide-rule overflow-hidden">
                                    {show(n.channels).map((c) => <ChannelCard key={c.id} c={c} />)}
                                </ul>
                            ) : (
                                <p className="tray px-4 py-3 text-xs text-muted">
                                    {n.channels.length ? 'No show here is green.' : 'No show found for this niche.'}
                                </p>
                            )}
                        </div>
                    ))}
                </section>
            )}
        </div>
    );
}
