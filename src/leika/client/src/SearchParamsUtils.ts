export const searchParamKey = "websocket";

function normalizedPath(pathname: string): string {
  return pathname === "/" ? "" : pathname.replace(/\/$/, "");
}

/** The WebSocket endpoint implied by the page URL. */
export function defaultWebsocketServer(pageUrl: string): string {
  const page = new URL(pageUrl);
  const protocol = page.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${page.host}${normalizedPath(page.pathname)}`;
}

function normalizedWebsocketServer(server: string): string | null {
  try {
    const url = new URL(server);
    if (url.protocol !== "ws:" && url.protocol !== "wss:") return null;
    return `${url.protocol}//${url.host}${normalizedPath(url.pathname)}${url.search}`;
  } catch {
    return null;
  }
}

export function isDefaultWebsocketServer(
  server: string,
  pageUrl: string,
): boolean {
  return normalizedWebsocketServer(server) === defaultWebsocketServer(pageUrl);
}

function encodeQueryPart(value: string): string {
  return encodeURIComponent(value)
    .replaceAll("%3A", ":")
    .replaceAll("%2F", "/");
}

/** Return the same page URL with its WebSocket override synchronized. */
export function urlWithWebsocketServer(
  pageUrl: string,
  server: string,
): string {
  const page = new URL(pageUrl);
  const searchParams = page.searchParams;

  if (isDefaultWebsocketServer(server, pageUrl)) {
    searchParams.delete(searchParamKey);
  } else {
    searchParams.set(searchParamKey, server);
  }

  const query = Array.from(searchParams.entries())
    .map(([key, value]) => `${encodeQueryPart(key)}=${encodeQueryPart(value)}`)
    .join("&");
  return `${page.pathname}${query === "" ? "" : `?${query}`}${page.hash}`;
}

export function syncSearchParamServer(server: string): void {
  // A srcdoc iframe has no navigable page URL of its own.
  if (window.location.protocol === "about:") return;
  window.history.replaceState(
    null,
    "Leika",
    urlWithWebsocketServer(window.location.href, server),
  );
}
