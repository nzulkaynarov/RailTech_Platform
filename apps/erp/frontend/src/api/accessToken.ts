/**
 * In-memory access-token holder (F2.1).
 *
 * The access token lives ONLY here (a module variable), never in localStorage — so
 * XSS can't read it, and it's gone on reload (a fresh one is minted from the HttpOnly
 * refresh cookie at startup). Kept in a tiny leaf module so both the axios client and
 * the auth store can touch it without an import cycle.
 */
let _accessToken: string | null = null;

export const getAccessToken = (): string | null => _accessToken;

export const setAccessToken = (token: string | null): void => {
    _accessToken = token;
};
