// Configuration for API endpoints
// If VITE_API_URL is set (e.g. in production), use it.
// Otherwise, default to empty string which means relative paths (proxied in dev).

export const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export const getApiUrl = (path) => {
    if (path.startsWith('http')) return path;
    // Split off the query string BEFORE per-segment encoding, or a caller
    // passing e.g. "...?niche=Joe%20Rogan" got '?', '=' and the already-escaped
    // '%20' all encoded again ('%3F', '%3D', '%2520') — FastAPI then saw one
    // opaque path segment instead of a query param and 404'd. Callers are
    // expected to have already encodeURIComponent'd their own query values.
    const [pathname, query] = path.split(/\?(.*)/s);
    // Ensure path starts with / if not present
    const normalizedPath = pathname.startsWith('/') ? pathname : `/${pathname}`;
    // Encode each segment: filenames can contain '#', spaces, etc. that must
    // not reach the URL unescaped (an unescaped '#' truncates the request at
    // the fragment, silently dropping the rest of the path before it's sent).
    const encodedPath = normalizedPath
        .split('/')
        .map(encodeURIComponent)
        .join('/');
    return `${API_BASE_URL}${encodedPath}${query !== undefined ? `?${query}` : ''}`;
};
