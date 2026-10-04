import { useEffect, useState } from 'react';
import { CalendarCheck } from 'lucide-react';
import { apiFetch } from '../lib/api';
import Modal from './ui/Modal';
import ScheduleComposer from './ScheduleComposer';

/**
 * "schedule clips" from the Clip Generator's results: the same scheduling
 * form as Publish Plan (ScheduleComposer), for the project on screen. It
 * reads the calendar so new slots continue after what's already planned.
 */
export default function ScheduleWeekModal({
    isOpen, onClose, project, uploadPostKey, uploadUserId, profiles = [], isManaged,
    lastNiche = '', onNicheChosen, onOpenPlan,
}) {
    const [entries, setEntries] = useState([]);

    const loadEntries = () => apiFetch('/api/schedule')
        .then((r) => (r.ok ? r.json() : { entries: [] }))
        .then((d) => setEntries(d.entries || []))
        .catch(() => setEntries([]));

    useEffect(() => {
        if (isOpen) loadEntries();
    }, [isOpen, project?.job_id]);

    if (!isOpen) return null;

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            eyebrow="Publish · Upload-Post"
            title="Schedule clips"
            size="xl"
            footer={(
                <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 sm:gap-3">
                    <button type="button" onClick={onClose} className="btn-ghost">Close</button>
                    {onOpenPlan && (
                        <button type="button" onClick={() => { onClose(); onOpenPlan(); }} className="btn-ghost">
                            <CalendarCheck size={15} aria-hidden="true" /> Open publish plan
                        </button>
                    )}
                </div>
            )}
        >
            <ScheduleComposer
                project={project}
                entries={entries}
                uploadPostKey={uploadPostKey}
                uploadUserId={uploadUserId}
                profiles={profiles}
                isManaged={isManaged}
                lastNiche={lastNiche}
                onNicheChosen={onNicheChosen}
                onScheduled={loadEntries}
            />
        </Modal>
    );
}
