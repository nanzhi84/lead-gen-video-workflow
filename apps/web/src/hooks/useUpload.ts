import { useCallback, useState } from "react";
import { api, type CompleteUploadResponse, type UploadKind, type UploadSession } from "../api/client";

type UploadStage = "idle" | "preparing" | "uploading" | "completing" | "completed" | "failed";

type UploadFileInput = {
  file: File;
  kind: UploadKind;
  caseId?: string | null;
  metadata?: Record<string, string>;
  stabilize?: boolean;
};

type UploadState = {
  status: UploadStage;
  progress: number;
  session?: UploadSession;
  result?: CompleteUploadResponse;
  error?: Error;
};

const initialState: UploadState = {
  status: "idle",
  progress: 0,
};

export function useUpload() {
  const [state, setState] = useState<UploadState>(initialState);

  const reset = useCallback(() => setState(initialState), []);

  const uploadFile = useCallback(async ({ file, kind, caseId = null, metadata, stabilize = false }: UploadFileInput) => {
    let prepared: UploadSession | undefined;
    try {
      setState({ status: "preparing", progress: 8 });
      prepared = await api.uploads.prepare({
        kind,
        case_id: caseId,
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        multipart: false,
        stabilize,
      });

      setState({ status: "uploading", progress: 42, session: prepared });
      const uploaded = await api.uploads.uploadFile(prepared.id, file);

      setState({ status: "completing", progress: 82, session: uploaded });
      const result = await api.uploads.complete({
        upload_session_id: uploaded.id,
        size_bytes: file.size,
        metadata,
      });

      setState({ status: "completed", progress: 100, session: result.upload_session, result });
      return result;
    } catch (error) {
      const normalized = error instanceof Error ? error : new Error("上传失败");
      if (prepared?.id) {
        await api.uploads.cancel(prepared.id).catch(() => undefined);
      }
      setState((current) => ({ ...current, status: "failed", error: normalized }));
      throw normalized;
    }
  }, []);

  return {
    ...state,
    reset,
    uploadFile,
  };
}
