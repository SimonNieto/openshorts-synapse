import React, { useState, useRef, useEffect } from 'react';
import { CreditCard, LogOut, Sparkles } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

// Header avatar + dropdown for signed-in cloud users: shows the email and gives
// access to Account & billing (manage subscription, top-ups) and Sign out.
export default function ProfileMenu() {
  const { user, isManaged, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  if (!user) return null;
  const initial = (user.email || '?').trim().charAt(0).toUpperCase();

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Account menu"
        aria-expanded={open}
        aria-controls="profile-menu-panel"
        className={`w-9 h-9 [@media(pointer:coarse)]:w-11 [@media(pointer:coarse)]:h-11 rounded-full border flex items-center justify-center text-sm font-semibold transition-colors ${open
          ? 'bg-ink text-paper border-ink'
          : 'bg-paper3 text-ink border-rule2 hover:border-ink'}`}
      >
        {initial}
      </button>

      {open && (
        <div id="profile-menu-panel" className="card-print absolute right-0 top-full mt-2 w-64 max-w-[calc(100vw-2rem)] z-30 overflow-hidden animate-fade">
          <div className="px-4 py-3 border-b border-rule">
            <p className="readout">Signed in as</p>
            <p className="text-sm text-ink truncate mt-1" title={user.email}>{user.email}</p>
          </div>
          <ul className="py-1">
            {!isManaged && (
              <li>
                <button
                  type="button"
                  onClick={() => { setOpen(false); window.location.hash = '#/pricing'; }}
                  className="w-full min-h-[44px] flex items-center gap-3 px-4 py-2.5 text-sm text-ink hover:bg-paper3 transition-colors"
                >
                  <Sparkles size={16} className="text-vermilion" aria-hidden="true" /> Start free
                </button>
              </li>
            )}
            <li>
              <button
                type="button"
                onClick={() => { setOpen(false); window.location.hash = '#/account'; }}
                className="w-full min-h-[44px] flex items-center gap-3 px-4 py-2.5 text-sm text-ink2 hover:text-ink hover:bg-paper3 transition-colors"
              >
                <CreditCard size={16} className="text-muted" aria-hidden="true" /> Account &amp; billing
              </button>
            </li>
            <li className="border-t border-rule mt-1 pt-1">
              <button
                type="button"
                onClick={() => { setOpen(false); logout(); }}
                className="w-full min-h-[44px] flex items-center gap-3 px-4 py-2.5 text-sm text-ink2 hover:text-ink hover:bg-paper3 transition-colors"
              >
                <LogOut size={16} className="text-muted" aria-hidden="true" /> Sign out
              </button>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}
