// The Firebase ID token travels in this cookie: the only one Firebase Hosting passes on
// to Cloud Run. The server checks it on every request; the API checks it again.
export const SESSION_COOKIE = "__session";
export const PUBLIC_PATHS = ["/login", "/signup", "/api/config"];
