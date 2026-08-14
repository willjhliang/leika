/** A string-key registry with no inherited names or legacy prototype setter. */
export function emptyRecord<T>(): Record<string, T> {
  return Object.create(null) as Record<string, T>;
}

/** Shallow-copy only own enumerable entries into an own-safe registry. */
export function cloneRecord<T>(source: Record<string, T>): Record<string, T> {
  const output = emptyRecord<T>();
  for (const [key, value] of Object.entries(source)) output[key] = value;
  return output;
}
