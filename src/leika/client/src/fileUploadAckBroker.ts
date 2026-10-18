import type {
  FileTransferAbort,
  FileTransferPartAck,
} from "./WebsocketMessages";

export const FILE_UPLOAD_ACK_TIMEOUT_MS = 30_000;

/** A failed upload, including whether the server still holds the transfer and
 * should be asked to let it go. */
export class FileUploadError extends Error {
  constructor(
    message: string,
    readonly notifyServer: boolean,
    readonly visible = true,
  ) {
    super(message);
    this.name = "FileUploadError";
  }
}

type Upload = {
  componentUuid: string;
  /** The sender's wait for the server's next acknowledgement. */
  waiter: {
    resolve: () => void;
    reject: (error: FileUploadError) => void;
  } | null;
  /** Why the upload ended early; every later wait fails with it. */
  failure: FileUploadError | null;
};

/** The sending half of one upload. */
export interface FileUploadAcknowledgements {
  /** Wait for the server to acknowledge everything sent so far. */
  acknowledged(timeoutMs: number): Promise<void>;
  /** End the upload early, failing its wait. */
  fail(error: FileUploadError): void;
  /** Forget the upload once its sender is done. */
  finish(): void;
}

/** Route the server's replies to the uploads in flight, by transfer ID. */
export class FileUploadAckBroker {
  private readonly uploads = new Map<string, Upload>();

  begin(
    transferUuid: string,
    componentUuid: string,
  ): FileUploadAcknowledgements {
    const upload: Upload = { componentUuid, waiter: null, failure: null };
    this.uploads.set(transferUuid, upload);
    return {
      acknowledged: (timeoutMs) =>
        new Promise<void>((resolve, reject) => {
          if (upload.failure !== null) {
            reject(upload.failure);
            return;
          }
          const timeout = setTimeout(
            () =>
              this.fail(
                upload,
                new FileUploadError(
                  "The server did not acknowledge the upload.",
                  true,
                ),
              ),
            timeoutMs,
          );
          upload.waiter = {
            resolve: () => {
              clearTimeout(timeout);
              resolve();
            },
            reject: (error) => {
              clearTimeout(timeout);
              reject(error);
            },
          };
        }),
      fail: (error) => this.fail(upload, error),
      finish: () => this.uploads.delete(transferUuid),
    };
  }

  /** Let an upload send its next part, answering with its control's ID. */
  acceptAck(message: FileTransferPartAck): string | null {
    const upload = this.uploads.get(message.transfer_uuid);
    if (upload === undefined) return null;
    const waiter = upload.waiter;
    upload.waiter = null;
    waiter?.resolve();
    return upload.componentUuid;
  }

  /** Stop the upload a server abort names; false when it names none. */
  acceptAbort(message: FileTransferAbort): boolean {
    const upload = this.uploads.get(message.transfer_uuid);
    if (upload === undefined) return false;
    this.fail(
      upload,
      new FileUploadError(
        message.reason || "The server stopped the upload.",
        false,
      ),
    );
    return true;
  }

  /** Fail every upload of a connection that is being replaced. */
  reset(reason: string): void {
    for (const upload of this.uploads.values()) {
      this.fail(upload, new FileUploadError(reason, false));
    }
  }

  private fail(upload: Upload, error: FileUploadError): void {
    if (upload.failure !== null) return;
    upload.failure = error;
    const waiter = upload.waiter;
    upload.waiter = null;
    waiter?.reject(error);
  }
}
