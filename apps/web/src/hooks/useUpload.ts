import { useCallback, useState } from "react";
import {
  api,
  putToOss,
  sha256Hex,
  type CompleteUploadResponse,
  type UploadKind,
  type UploadSession,
} from "../api/client";

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

// Browsers sometimes report an empty File.type; fall back to the extension so the
// server's per-kind content-type allowlist still gets a real MIME (not octet-stream).
const EXTENSION_CONTENT_TYPES: Record<string, string> = {
  mp4: "video/mp4", mov: "video/quicktime", webm: "video/webm",
  png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp",
  mp3: "audio/mpeg", wav: "audio/wav", m4a: "audio/mp4", aac: "audio/aac",
  ttf: "font/ttf", otf: "font/otf", woff: "font/woff", woff2: "font/woff2",
};

function guessContentType(file: File): string {
  if (file.type) return file.type;
  const ext = file.name.split(".").pop()?.toLowerCase();
  return (ext && EXTENSION_CONTENT_TYPES[ext]) || "application/octet-stream";
}

export function useUpload() {
  const [state, setState] = useState<UploadState>(initialState);

  const reset = useCallback(() => setState(initialState), []);

  const uploadFile = useCallback(
    async ({ file, kind, caseId = null, metadata, stabilize = false }: UploadFileInput) => {
      let sessionId: string | undefined;
      try {
        setState({ status: "preparing", progress: 0 });
        // Hash client-side so the API can verify the object after the direct PUT.
        const sha256 = await sha256Hex(file);
        const ticket = await api.uploads.prepare({
          kind,
          case_id: caseId,
          filename: file.name,
          content_type: guessContentType(file),
          size_bytes: file.size,
          sha256,
          stabilize,
        });
        const session = ticket.upload_session;
        sessionId = session.id;

        // Browser -> OSS directly; the API never sees the bytes.
        setState({ status: "uploading", progress: 0, session });
        await putToOss(ticket.put_url, file, ticket.put_content_type, (loaded, total) =>
          setState({
            status: "uploading",
            progress: total ? Math.round((loaded / total) * 100) : 0,
            session,
          }),
        );

        setState({ status: "completing", progress: 99, session });
        const result = await api.uploads.complete({
          upload_session_id: session.id,
          size_bytes: file.size,
          sha256,
          metadata,
        });

        setState({ status: "completed", progress: 100, session: result.upload_session, result });
        return result;
      } catch (error) {
        const normalized = error instanceof Error ? error : new Error("上传失败");
        if (sessionId) {
          await api.uploads.cancel(sessionId).catch(() => undefined);
        }
        setState((current) => ({ ...current, status: "failed", error: normalized }));
        throw normalized;
      }
    },
    [],
  );

  return {
    ...state,
    reset,
    uploadFile,
  };
}
