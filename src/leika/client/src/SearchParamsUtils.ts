/** The WebSocket endpoint for a page: its `?websocket=` override, or the
 * server that served the page. */
export function websocketServer(pageUrl: string): string {
  const page = new URL(pageUrl);
  const override = page.searchParams.get("websocket");
  if (override !== null) return override;
  const protocol = page.protocol === "https:" ? "wss:" : "ws:";
  const path = page.pathname === "/" ? "" : page.pathname.replace(/\/$/, "");
  return `${protocol}//${page.host}${path}`;
}
