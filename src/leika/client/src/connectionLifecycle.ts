export interface ConnectionOwnerReset {
  resetGui(): void;
  resetPanes(): void;
  resetResources(): void;
}

/** Drop mounted connection owners before invalidating their shared ledgers. */
export function resetConnectionOwners({
  resetGui,
  resetPanes,
  resetResources,
}: ConnectionOwnerReset): void {
  resetGui();
  resetPanes();
  resetResources();
}
