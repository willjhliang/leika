import { Spinner } from "../components/ui/spinner";

export function ViewportPaneLoadingOverlay({
  loading,
}: {
  loading: true | string;
}) {
  const label =
    typeof loading === "string" && loading.length > 0 ? loading : "Loading";
  return (
    <div
      data-viewport-pane-loading
      role="status"
      aria-live="polite"
      aria-atomic="true"
      aria-label={label}
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 10,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "0.5rem",
        padding: "1rem",
        color: "var(--muted-foreground)",
        fontSize: "var(--text-sm)",
        textAlign: "center",
        background: "var(--background)",
      }}
    >
      <Spinner aria-hidden="true" />
      {typeof loading === "string" ? <span>{loading}</span> : null}
    </div>
  );
}
