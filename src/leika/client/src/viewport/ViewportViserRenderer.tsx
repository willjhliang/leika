import React from "react";
import { Spinner } from "../components/ui/spinner";
import { useColorScheme } from "../hooks/useColorScheme";
import type { ViewportViserPane } from "./ViewportState";

/** Live viser scene embed: viser's own client in an iframe. The iframe is
 * keyed by its resolved URL, so re-pointing the pane — and flipping Leika's
 * theme, which changes the darkMode parameter — remounts it, resetting the
 * scene connection and camera state rather than navigating in place. */
export function ViewportViserRenderer({ pane }: { pane: ViewportViserPane }) {
  // Viser renders the darkMode URL flag, so the embed follows Leika's theme.
  const colorScheme = useColorScheme();
  const src = React.useMemo(() => {
    // A same-origin proxy path or an absolute URL, used near-verbatim (new
    // URL() normalizes, e.g. adding a trailing slash).
    const base = pane.props._url;
    try {
      // Viser's darkMode flag is presence-based, so following Leika's theme
      // means removing it as well as adding it.
      const url = new URL(base, window.location.href);
      if (colorScheme === "dark") url.searchParams.set("darkMode", "");
      else url.searchParams.delete("darkMode");
      return url.toString();
    } catch {
      // Python's URL validation is looser than the browser's; a string the
      // browser cannot parse must not take down the workspace. As a plain
      // iframe src it just fails to load, minus theme forwarding.
      return base;
    }
  }, [pane.props._url, colorScheme]);
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: "var(--background)",
      }}
    >
      <ViewportViserFrame key={src} src={src} title={pane.props.title} />
    </div>
  );
}

export function ViewportViserFrame({
  src,
  title,
}: {
  src: string;
  title: string;
}) {
  const [loaded, setLoaded] = React.useState(false);
  return (
    <>
      {/* No sandbox: viser's client needs scripts, web workers, and
       * same-origin storage. Cross-origin frames emit load for error pages
       * too and no signal at all for network failures, so the overlay below
       * is best-effort: it clears on load and otherwise stays. */}
      <iframe
        src={src}
        title={title}
        referrerPolicy="no-referrer"
        allow="fullscreen; clipboard-write"
        onLoad={() => setLoaded(true)}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          border: 0,
          display: "block",
          background: "var(--background)",
        }}
      />
      {loaded ? null : (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "0.5rem",
            color: "var(--muted-foreground)",
            fontSize: "var(--text-sm)",
            background: "var(--background)",
          }}
        >
          <Spinner />
          Loading viser…
        </div>
      )}
    </>
  );
}
