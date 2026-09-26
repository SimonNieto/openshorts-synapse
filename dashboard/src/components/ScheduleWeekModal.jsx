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
            eyebrow="PUBLISH · UPLOAD-POST"
            title="schedule clips"
            size="xl"
            footer={(
                <div className="flex gap-3 justify-end">
                    <button onClick={onClose} className="btn-ghost px-4 py-2 text-sm">close</button>
                    {onOpenPlan && (
                        <button onClick={() => { onClose(); onOpenPlan(); }} className="btn-quiet px-4 py-2 text-sm inline-flex items-center gap-2">
                            <CalendarCheck size={15} /> open publish plan
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
