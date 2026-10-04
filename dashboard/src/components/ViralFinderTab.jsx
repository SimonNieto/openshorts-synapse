import React, { useState } from 'react';
import { Loader2, Search, ExternalLink, AlertCircle } from 'lucide-react';
import { apiJson } from '../lib/api';

function formatViews(n) {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, '')}K`;
    return String(n);
}

// Presentation only: the API already returns publishedAt (ISO 8601).
function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

// A ready-made list of the most-viewed Shorts in a niche (YouTube Data API),
// so a repost/clipping channel has source material to watch and pick from
// instead of hunting for it by hand. Links out to watch on YouTube — nothing
// here downloads or embeds the video itself.
export default function ViralFinderTab() {
    const [niche, setNiche] = useState(() => {
        try { return localStorage.getItem('openshorts_niche') || ''; } catch { return ''; }
    });
    const [includeShorts, setIncludeShorts] = useState(true);
    const [includeVideos, setIncludeVideos] = useState(false);
    const [shorts, setShorts] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSearch = async (e) => {
        e.preventDefault();
        if (!niche.trim() || loading) return;
        setLoading(true);
        setError('');
        setShorts(null);
        try {
            const data = await apiJson('/api/viral-shorts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    niche, max_results: 20,
                    include_shorts: includeShorts, include_videos: includeVideos,
                }),
            });
            setShorts(data.shorts || []);
        } catch (e) {
            setError(e.detail || e.message || 'Search failed');
        } finally {
            setLoading(false);
        }
    };

    // Neither checked would silently search nothing useful — keep one
    // always on by re-checking "Shorts" instead of letting this go empty.
    const toggleShorts = () => {
        setIncludeShorts((v) => {
            const next = !v;
            if (!next && !includeVideos) setIncludeVideos(true);
            return next;
        });
    };
    const toggleVideos = () => {
        setIncludeVideos((v) => {
            const next = !v;
            if (!next && !includeShorts) setIncludeShorts(true);
            return next;
        });
    };

    const filterChip = (on) => `inline-flex items-center gap-2.5 min-h-[44px] px-3.5 rounded-input border cursor-pointer select-none text-sm transition-colors duration-200 ${on
        ? 'border-ink bg-paper3 text-ink'
        : 'border-rule2 text-ink2 hover:border-ink hover:text-ink'
        }`;

    return (
        <div className="space-y-8 animate-fade">
            <header className="max-w-2xl">
                <p className="eyebrow mb-2">Research</p>
                <h2 className="page-title">Find what already works</h2>
                <p className="page-lede mt-3">
                    Type a niche to see its most-viewed Shorts right now, straight from the YouTube Data API. Watch the
                    ones that stand out, then feed the best into the Viral Clip Reworker if it's worth reposting.
                </p>
            </header>

            <section aria-labelledby="vf-search-heading" className="card-print p-4 sm:p-6">
                <h3 id="vf-search-heading" className="sr-only">Search a niche</h3>
                <form onSubmit={handleSearch} role="search" aria-label="Find viral shorts" className="space-y-5">
                    <div>
                        <label htmlFor="vf-niche" className="block text-sm font-medium text-ink mb-2">Niche or topic</label>
                        <div className="flex flex-col sm:flex-row gap-3">
                            <input
                                id="vf-niche"
                                type="text"
                                value={niche}
                                onChange={(e) => setNiche(e.target.value)}
                                className="input-field flex-1 min-w-0"
                                placeholder="e.g. Joe Rogan podcast clips"
                            />
                            <button type="submit" disabled={!niche.trim() || loading} className="btn-accent shrink-0">
                                {loading
                                    ? <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                                    : <Search size={16} aria-hidden="true" />}
                                {loading ? 'Searching…' : 'Find viral shorts'}
                            </button>
                        </div>
                    </div>

                    <fieldset>
                        <legend className="readout mb-2">Include</legend>
                        <div className="flex flex-wrap gap-2">
                            <label className={filterChip(includeShorts)}>
                                <input type="checkbox" checked={includeShorts} onChange={toggleShorts} className="w-4 h-4 accent-ink" />
                                Shorts
                            </label>
                            <label className={filterChip(includeVideos)}>
                                <input type="checkbox" checked={includeVideos} onChange={toggleVideos} className="w-4 h-4 accent-ink" />
                                Videos
                            </label>
                        </div>
                    </fieldset>

                    {error && (
                        <div role="alert" className="flex items-start gap-2.5 rounded-input border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink">
                            <AlertCircle size={16} className="text-danger shrink-0 mt-0.5" aria-hidden="true" />
                            <span className="break-words">{error}</span>
                        </div>
                    )}
                </form>
            </section>

            <section aria-labelledby="vf-results-heading" aria-busy={loading} className="space-y-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-rule2 pb-3">
                    <h3 id="vf-results-heading" className="font-display text-xl text-ink">Results</h3>
                    <p className="readout" aria-live="polite">
                        {loading ? 'Searching…' : shorts ? `${shorts.length} found · most viewed first` : ''}
                    </p>
                </div>

                {!shorts && !loading && (
                    <div className="tray px-5 py-10 text-center">
                        <p className="text-sm text-ink2">Results land here, ranked by real view count.</p>
                        <p className="text-xs text-muted mt-1">Nothing is downloaded: each one opens on YouTube.</p>
                    </div>
                )}

                {loading && (
                    <ul className="card divide-y divide-rule overflow-hidden" aria-hidden="true">
                        {[0, 1, 2, 3].map((k) => (
                            <li key={k} className="flex items-center gap-4 p-3 sm:p-4">
                                <span className="w-28 sm:w-40 aspect-video rounded-input bg-paper3 animate-pulse shrink-0" />
                                <span className="flex-1 space-y-2">
                                    <span className="block h-3 rounded bg-paper3 animate-pulse w-4/5" />
                                    <span className="block h-3 rounded bg-paper3 animate-pulse w-2/5" />
                                </span>
                            </li>
                        ))}
                    </ul>
                )}

                {shorts && shorts.length === 0 && (
                    <div className="tray px-5 py-10 text-center">
                        <p className="text-sm text-ink2">No Shorts found for this niche.</p>
                        <p className="text-xs text-muted mt-1">Try a broader topic, or include regular videos.</p>
                    </div>
                )}

                {shorts && shorts.length > 0 && (
                    <ol className="card divide-y divide-rule overflow-hidden">
                        {shorts.map((s, i) => {
                            const published = formatDate(s.publishedAt);
                            return (
                                <li key={s.videoId}>
                                    <a
                                        href={s.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="group grid grid-cols-[7rem_minmax(0,1fr)] sm:grid-cols-[2rem_10rem_minmax(0,1fr)_auto] items-center gap-x-3 sm:gap-x-5 p-3 sm:p-4 hover:bg-paper3 transition-colors duration-200"
                                    >
                                        <span className="hidden sm:block font-mono text-xs text-muted text-right" aria-hidden="true">
                                            {String(i + 1).padStart(2, '0')}
                                        </span>
                                        <span className="relative block aspect-video rounded-input overflow-hidden bg-black border border-rule2">
                                            {s.thumbnailUrl && (
                                                <img src={s.thumbnailUrl} alt="" className="w-full h-full object-cover" loading="lazy" />
                                            )}
                                        </span>
                                        <span className="min-w-0">
                                            <span className="block text-sm sm:text-[15px] font-medium text-ink leading-snug line-clamp-2 group-hover:underline underline-offset-2" title={s.title}>
                                                {s.title}
                                            </span>
                                            <span className="block text-xs text-muted mt-1 truncate">{s.channelTitle}</span>
                                            <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 mt-1.5">
                                                {includeShorts && includeVideos && (
                                                    <span className="readout border border-rule2 rounded-[4px] px-1.5 py-px">
                                                        {s.videoType === 'video' ? 'Video' : 'Short'}
                                                    </span>
                                                )}
                                                {published && <span className="readout">{published}</span>}
                                                <ExternalLink size={12} className="text-muted opacity-0 group-hover:opacity-100 transition-opacity" aria-hidden="true" />
                                            </span>
                                            {/* Phone: the views sit under the title */}
                                            <span className="sm:hidden flex items-baseline gap-1.5 mt-1.5">
                                                <span className="font-quote text-2xl leading-none text-ink">{formatViews(s.viewCount)}</span>
                                                <span className="readout">views</span>
                                            </span>
                                        </span>
                                        <span className="hidden sm:flex flex-col items-end pl-2">
                                            <span className="font-quote text-4xl leading-none text-ink">{formatViews(s.viewCount)}</span>
                                            <span className="readout mt-1.5">views</span>
                                        </span>
                                        <span className="sr-only">(opens YouTube in a new tab)</span>
                                    </a>
                                </li>
                            );
                        })}
                    </ol>
                )}
            </section>
        </div>
    );
}
