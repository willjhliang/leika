import { afterEach, expect, test } from "vitest";
import {
  cachedPreviewDocument,
  cachedPreviewText,
  rememberPreviewDocument,
  rememberPreviewText,
  resetPreviewDocumentCache,
} from "./previewDocumentCache";
import { renderMarkdown } from "./components/markdownDocument";

afterEach(resetPreviewDocumentCache);

test("completed large previews are reusable and evict the oldest source under pressure", () => {
  const document = renderMarkdown("# Report");
  const first = "a".repeat(600_000);
  const second = "b".repeat(600_000);
  rememberPreviewDocument(first, document);
  expect(cachedPreviewDocument(first)).toBe(document);
  rememberPreviewDocument(second, document);
  expect(cachedPreviewDocument(first)).toBeNull();
  expect(cachedPreviewDocument(second)).toBe(document);
  expect(cachedPreviewDocument(second + "changed")).toBeNull();
});

test("decoded text follows exact Blob identity and connection reset clears all reuse", () => {
  const blob = new Blob(["# Report"]);
  const document = renderMarkdown("# Report");
  rememberPreviewText(blob, "# Report");
  rememberPreviewDocument("# Report", document);
  expect(cachedPreviewText(blob)).toBe("# Report");
  expect(cachedPreviewText(new Blob(["# Report"]))).toBeNull();
  resetPreviewDocumentCache();
  expect(cachedPreviewText(blob)).toBeNull();
  expect(cachedPreviewDocument("# Report")).toBeNull();
});
