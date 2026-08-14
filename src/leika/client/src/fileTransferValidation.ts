export const FILE_TRANSFER_IDENTIFIER_MAX_CHARACTERS = 128;
export const FILE_TRANSFER_MIME_TYPE_MAX_CHARACTERS = 255;
export const FILE_TRANSFER_FILENAME_MAX_CHARACTERS = 255;
export const FILE_TRANSFER_FILENAME_MAX_UTF8_BYTES = 1_024;

const CONTROL_OR_FORMAT = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/u;

/** Match Python's protocol identifier boundary: nonempty printable ASCII. */
export function validFileTransferIdentifier(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > FILE_TRANSFER_IDENTIFIER_MAX_CHARACTERS
  )
    return false;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 32 || code >= 127) return false;
  }
  return true;
}

/** Match the server's wire MIME boundary; an empty File.type is legitimate. */
export function validFileTransferMimeType(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    value.length > FILE_TRANSFER_MIME_TYPE_MAX_CHARACTERS
  )
    return false;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) return false;
  }
  return true;
}

/** Match `validate_file_display_name`: a short Unicode display basename. */
export function validFileTransferFilename(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > FILE_TRANSFER_FILENAME_MAX_CHARACTERS * 2 ||
    value.trim().length === 0 ||
    [...value].length > FILE_TRANSFER_FILENAME_MAX_CHARACTERS ||
    value === "." ||
    value === ".." ||
    value.includes("/") ||
    value.includes("\\") ||
    CONTROL_OR_FORMAT.test(value)
  )
    return false;
  return (
    new TextEncoder().encode(value).byteLength <=
    FILE_TRANSFER_FILENAME_MAX_UTF8_BYTES
  );
}
