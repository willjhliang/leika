// Standard DOM the bundled `lib.dom` does not describe yet.
declare global {
  interface FocusOptions {
    /** Whether the focus ring is drawn. Left to the browser when omitted,
     * which guesses from the last thing the viewer touched -- and guesses
     * wrong for a `focus()` that follows a pointer gesture. A browser that
     * does not know the option simply goes on guessing. */
    focusVisible?: boolean;
  }
}

export {};
