import * as React from "react";

import { type ImageAdmission, LatestBlobImageInspector } from "../imageSafety";

export function useSafeBlobImage(blob: Blob | null, mimeType: string) {
  const inspector = React.useMemo(() => new LatestBlobImageInspector(), []);
  const [read, setRead] = React.useState<{
    blob: Blob;
    mimeType: string;
    admission: ImageAdmission;
  } | null>(null);
  React.useEffect(() => {
    setRead(null);
    if (blob === null) {
      inspector.clear();
      return;
    }
    return inspector.request(blob, mimeType, (admission) => {
      setRead({ blob, mimeType, admission });
    });
  }, [blob, inspector, mimeType]);
  return read?.blob === blob && read.mimeType === mimeType
    ? read.admission
    : null;
}
