import React from 'react';
import { AlertCircle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

/**
 * Shown wherever tiktok is among the selected platforms, before the button
 * that posts or schedules.
 *
 * Two different people need it. Someone who publishes one clip expects a live
 * post and finds nothing on their profile, and reads that as a failure. Someone
 * who schedules a week gets a silent drawer of drafts and a profile that stays
 * empty for seven days.
 *
 * The title/description line is not a detail: TikTok's upload-to-inbox endpoint
 * takes only source_info (the bytes), with no post_info anywhere in the request,
 * so the caption we send is dropped on the floor for a video draft — whether the
 * user typed it or the AI wrote it. Saying only "it arrives as a draft" leaves
 * them to discover that in the app.
 *
 * Lead with the upside: finishing the post inside TikTok is what the algorithm
 * rewards, so this is a better default, not a limitation we are apologising for.
 */
export default function TikTokDraftNotice() {
    // Only true under MEDIA_UPLOAD: with TIKTOK_POST_MODE=DIRECT_POST the
    // post goes live on schedule, caption and hashtags included.
    const { tiktokPostMode } = useAuth();
    if (tiktokPostMode !== 'MEDIA_UPLOAD') return null;
    return (
        <div role="note" className="tray mb-4 px-3 py-2.5 flex items-start gap-2.5 text-[13px] leading-relaxed text-ink2">
            <AlertCircle size={15} className="mt-0.5 shrink-0 text-muted" aria-hidden="true" />
            <p className="min-w-0">
                TikTok receives it as a <strong className="font-semibold text-ink">draft</strong>, not
                a live post — you'll get a notification in the app. Its API doesn't carry the
                title or description onto a draft, so you write those there, along with
                trending sounds, effects and hashtags. That reaches more people than posting
                straight from an API.
            </p>
        </div>
    );
}
