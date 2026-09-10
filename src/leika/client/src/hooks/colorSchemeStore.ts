export type ColorScheme = "light" | "dark";

/** The root class already resolves server, OS and embedded-workspace theme. */
export function getColorScheme(): ColorScheme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

const listeners = new Set<() => void>();
let observer: MutationObserver | null = null;

/** Every plot reads the same root. One observer avoids allocating and invoking
 * a native MutationObserver for every mounted plot when its classes change. */
export function subscribeColorScheme(onChange: () => void): () => void {
  if (typeof document === "undefined") return () => undefined;
  if (observer === null) {
    let previous = getColorScheme();
    const instance = new MutationObserver(() => {
      if (observer !== instance) return;
      const next = getColorScheme();
      if (next === previous) return;
      previous = next;
      for (const listener of listeners) listener();
    });
    observer = instance;
    instance.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }
  const listener = () => onChange();
  listeners.add(listener);
  let subscribed = true;
  return () => {
    if (!subscribed) return;
    subscribed = false;
    listeners.delete(listener);
    if (listeners.size === 0) {
      observer?.disconnect();
      observer = null;
    }
  };
}
