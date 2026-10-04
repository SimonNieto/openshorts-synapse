import React, { useEffect, useState } from 'react';
import { BarChart3, ExternalLink } from 'lucide-react';
import { apiJson } from '../lib/api';

const fmtNum = (n) => new Intl.NumberFormat('en-US', {
  notation: (n || 0) >= 10000 ? 'compact' : 'standard',
  maximumFractionDigits: 1,
}).format(n || 0);

// Upload-Post metric shapes vary per platform; read the first count that exists.
const postViews = (p) => {
  const m = p.post_metrics || p.metrics || p;
  return Number(m.views || m.impressions || m.plays || 0) || 0;
};
const postTitle = (p) => p.title || p.caption || p.youtube_title || p.tiktok_title || 'Untitled post';
const postUrl = (p) => p.post_url || p.url || p.share_url || null;

// Post-publication analytics: what the clips actually did out there.
// Paid-only by nature (social posting itself is paid in cloud): a 402 or any
// other failure simply hides the card — the account page works without it.
export default function SocialAnalyticsCard() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [imp, postsResp] = await Promise.all([
          apiJson('/api/social/analytics/impressions?period=last_month&breakdown=true'),
          apiJson('/api/social/analytics/posts?limit=50'),
        ]);
        if (!alive) return;
        const posts = (postsResp.posts || postsResp.data || postsResp.items || [])
          .slice()
          .sort((a, b) => postViews(b) - postViews(a));
        setData({ imp, posts });
      } catch (_) { /* free plan, nothing connected, or vendor hiccup — stay hidden */ }
    })();
    return () => { alive = false; };
  }, []);

  if (!data) return null;

  const total = data.imp?.total_impressions
    || data.posts.reduce((s, p) => s + postViews(p), 0);
  const perPlatform = Object.entries(data.imp?.per_platform || {})
    .filter(([, v]) => Number(v) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  const top = data.posts.slice(0, 3);

  return (
    <section aria-labelledby="social-analytics-title" className="card p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-4">
        <h3 id="social-analytics-title" className="font-display text-lg text-ink flex items-center gap-2">
          <BarChart3 size={16} className="text-muted" aria-hidden="true" /> Your posts
        </h3>
        <span className="readout">Last 30 days</span>
      </div>

      {data.posts.length === 0 && !total ? (
        <p className="text-muted text-sm">
          Nothing published yet. Post a clip from your results and its views show up here.
        </p>
      ) : (
        <>
          <p className="flex items-baseline gap-2.5 mb-4">
            <span className="font-quote text-5xl text-ink leading-none">{fmtNum(total)}</span>
            <span className="text-muted text-sm">impressions</span>
          </p>

          {perPlatform.length > 0 && (
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-3 mb-5">
              {perPlatform.map(([platform, v]) => (
                <div key={platform} className="min-w-0">
                  <dt className="readout truncate">{platform}</dt>
                  <dd className="text-sm text-ink mt-0.5">{fmtNum(Number(v))}</dd>
                </div>
              ))}
            </dl>
          )}

          {top.length > 0 && (
            <div className="border-t border-rule pt-4">
              <p className="readout mb-2">Top posts</p>
              <ol className="space-y-2.5">
                {top.map((p, i) => (
                  <li key={p.request_id || p.platform_post_id || i}
                      className="flex items-center justify-between gap-3 text-sm">
                    <span className="text-ink2 min-w-0 flex items-center gap-1.5">
                      <span className="truncate">{postTitle(p)}</span>
                      {postUrl(p) && (
                        <a href={postUrl(p)} target="_blank" rel="noreferrer"
                           aria-label={`Open “${postTitle(p)}” (new tab)`}
                           className="shrink-0 inline-flex items-center justify-center p-1 -m-1 rounded-input text-muted hover:text-ink transition-colors [@media(pointer:coarse)]:min-h-[44px] [@media(pointer:coarse)]:min-w-[44px]">
                          <ExternalLink size={13} aria-hidden="true" />
                        </a>
                      )}
                    </span>
                    <span className="readout !text-ink2 shrink-0">{fmtNum(postViews(p))} views</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </section>
  );
}
