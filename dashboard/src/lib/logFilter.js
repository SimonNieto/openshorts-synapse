// Splits a job's raw log lines in two: the few that say what is happening
// ("key") and the pipeline chatter ("noise": per-second transcript dump,
// TensorFlow / matplotlib warnings, encoder details, scene-detection bars...).
// The panel shows "key" by default and everything on demand.

// Whatever matches one of these is kept in the key view.
const KEY = [
    /^Job (started|queued)/i,
    /^Process (finished|failed)/i,
    /^Execution error|^No metadata/i,
    /^⏹/,                                   // stop requested / stopped by the user
    /^🎙️? ?Transcribing… \d+%/,             // transcription progress
    /^🎙️? ?Transcrib/,                      // transcription start / end
    /^Built \d+ scoring window/i,
    /^📖|^🎯/,                              // brief + scoring
    /^\s*Shortlisted /i,
    /^⚖️|^•/,                               // final judge + why each clip was kept
    /^📋/,                                  // windows report header
    /^[*>]?\s*\d{1,3}:\d{2}-\d{1,3}:\d{2}\s/, // windows report rows
    /^💰|Selection \(/,                     // selection cost
    /^🔥|Found \d+ viral clips/i,
    /^🎬 (Processing|Creating) clip/i,
    /^✅ Clip \d+ ready|Clip \d+ ready/i,
    /^🧠/,                                  // who is thinking
    /^🖼️|^🔎|^💡/,                          // b-roll: images, checks, thesis
    /^🎬 Edit style/,
    /^🎵/,
    /^⚠️|^❌|^🛑/,                          // warnings and errors
    /error|failed|exception/i,
];

// Never key, even when a key pattern would match by accident.
const NOISE = [
    /^\[\d+(\.\d+)?s -> \d+(\.\d+)?s\]/,    // "[996.50s -> 1003.22s] words..." transcript dump
    /^Analyzing Scenes/i,
    /^W\d{4} |^WARNING: All log|^INFO: Created TensorFlow|^Matplotlib|^mkdir -p failed/,
    /UserWarning|tensor = torch/,
    /^🚀 Reframe engine|^🎞️ \[Encoder\]|^🎬 Scene engine|^🎥 Smooth camera|^👀 Reactions/,
    /^✅ (Clip saved|Hook added)/,
];

export function isKeyLog(line) {
    const s = String(line || '').trim();
    if (!s) return false;
    if (NOISE.some((re) => re.test(s))) return false;
    return KEY.some((re) => re.test(s));
}

export function splitLogs(logs) {
    const key = (logs || []).filter(isKeyLog);
    return { key, all: logs || [] };
}
