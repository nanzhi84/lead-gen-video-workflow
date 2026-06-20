import { useMutation } from "@tanstack/react-query";
import { Loader2, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PublishPlatform } from "../../api/client";
import { Modal } from "../ui/Modal";
import { LoadingState } from "../ui/State";
import { useToast } from "../ui/Toast";

type QrLoginAccount = {
  id: string;
  account_name: string;
  platform: PublishPlatform;
};

type QrLoginDialogProps = {
  account: QrLoginAccount;
  onClose: () => void;
  onSuccess: () => void;
};

// Mirrors the backend ``LoginStreamEvent`` contract pushed over the login WebSocket.
type LoginStreamEvent = {
  type: "qr" | "status" | "account" | "error";
  qr_image?: string | null;
  status?: string | null;
  detail?: string | null;
};

const platformLabels: Record<PublishPlatform, string> = {
  douyin: "抖音",
  shipinhao: "视频号",
  kuaishou: "快手",
  xiaohongshu: "小红书",
};

const platformApps: Record<PublishPlatform, string> = {
  douyin: "抖音 App",
  shipinhao: "微信",
  kuaishou: "快手 App",
  xiaohongshu: "小红书 App",
};

function buildStreamUrl(streamPath: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${streamPath}`;
}

export function QrLoginDialog({ account, onClose, onSuccess }: QrLoginDialogProps) {
  const toast = useToast();
  const [qrImage, setQrImage] = useState<string | null>(null);
  const [verifying, setVerifying] = useState<string | null>(null);
  const [failedDetail, setFailedDetail] = useState<string | null>(null);
  const loginIdRef = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const beginSequenceRef = useRef(0);
  const disposedRef = useRef(false);
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;

  const cancelLogin = useCallback(
    async (targetLoginId: string) => {
      await api.publishOps.cancelLogin(account.id, targetLoginId).catch(() => undefined);
    },
    [account.id],
  );

  const closeSocket = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const teardown = useCallback(
    async (clearState = true) => {
      const currentLoginId = loginIdRef.current;
      beginSequenceRef.current += 1;
      loginIdRef.current = null;
      closeSocket();
      if (clearState) {
        setQrImage(null);
        setVerifying(null);
      }
      if (currentLoginId) {
        await cancelLogin(currentLoginId);
      }
    },
    [cancelLogin, closeSocket],
  );

  const handleClose = useCallback(() => {
    void teardown();
    onClose();
  }, [teardown, onClose]);

  const succeed = useCallback(() => {
    toast.success("登录成功", account.account_name);
    onSuccessRef.current();
    handleClose();
  }, [account.account_name, handleClose, toast]);

  const beginLogin = useMutation({
    mutationFn: async (sequence: number) => ({
      response: await api.publishOps.beginLogin(account.id),
      sequence,
    }),
    onSuccess: ({ response, sequence }) => {
      if (disposedRef.current || sequence !== beginSequenceRef.current) {
        void cancelLogin(response.login_id);
        return;
      }
      loginIdRef.current = response.login_id;
      setFailedDetail(null);
      setVerifying(null);
      setQrImage(null);
      // The QR is streamed in real time over the WebSocket — 小V猫's platform code
      // refreshes fast, so the socket pushes each fresh frame (no polling).
      const ws = new WebSocket(buildStreamUrl(response.stream_path));
      wsRef.current = ws;
      ws.onmessage = (event) => {
        if (sequence !== beginSequenceRef.current) return;
        let data: LoginStreamEvent;
        try {
          data = JSON.parse(event.data) as LoginStreamEvent;
        } catch {
          return;
        }
        if (data.type === "qr" && data.qr_image) {
          setQrImage(data.qr_image);
          setVerifying(null);
        } else if (data.type === "status") {
          if (data.status === "active") succeed();
          else if (data.status === "verifying")
            setVerifying(data.detail || "请在手机上完成平台安全验证后继续。");
          else if (data.status === "failed")
            setFailedDetail(data.detail || "二维码已失效或登录失败，请重新获取。");
        } else if (data.type === "account") {
          succeed();
        } else if (data.type === "error") {
          setFailedDetail(data.detail || "登录失败，请重新获取二维码。");
        }
      };
      ws.onerror = () => {
        if (sequence === beginSequenceRef.current) {
          setFailedDetail("实时连接中断，请重新获取二维码。");
        }
      };
    },
    onError: (error, sequence) => {
      if (sequence !== beginSequenceRef.current || disposedRef.current) return;
      loginIdRef.current = null;
      setQrImage(null);
      toast.error("登录启动失败", error);
    },
  });
  const { mutate: beginLoginMutate } = beginLogin;

  const startLogin = useCallback(() => {
    const sequence = beginSequenceRef.current + 1;
    beginSequenceRef.current = sequence;
    beginLoginMutate(sequence);
  }, [beginLoginMutate]);

  useEffect(() => {
    disposedRef.current = false;
    startLogin();
    return () => {
      disposedRef.current = true;
      void teardown(false);
    };
  }, [startLogin, teardown]);

  async function refreshQr() {
    await teardown();
    setFailedDetail(null);
    startLogin();
  }

  const platformLabel = platformLabels[account.platform];
  const platformApp = platformApps[account.platform];

  return (
    <Modal isOpen onClose={handleClose} title="扫码登录" size="sm">
      <div className="grid gap-5">
        <div className="rounded-2xl border border-border/70 bg-white/65 p-4">
          <p className="text-sm font-semibold text-text-primary">
            {platformLabel} · {account.account_name}
          </p>
          <p className="mt-1 text-xs leading-5 text-text-secondary">
            请用对应 App 扫码登录（抖音→抖音App / 视频号→微信 / 快手→快手App / 小红书→小红书App）。
            当前账号请使用 {platformApp}。二维码经小V猫实时刷新，无需手动重取。
          </p>
        </div>

        <div className="grid place-items-center rounded-[24px] border border-border/70 bg-white/80 p-5">
          {beginLogin.isPending && !qrImage ? <LoadingState label="正在准备二维码" /> : null}
          {qrImage ? (
            <img
              src={qrImage}
              alt="登录二维码"
              className="h-64 w-64 rounded-2xl border border-border/70 bg-white object-contain p-3"
            />
          ) : null}
          {!beginLogin.isPending && !qrImage && !failedDetail ? (
            <div className="stateBox muted">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>等待小V猫推送二维码</span>
            </div>
          ) : null}
        </div>

        {qrImage && !verifying && !failedDetail ? (
          <div className="stateBox muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>等待扫码确认</span>
          </div>
        ) : null}

        {verifying ? (
          <div className="stateBox warning">
            <ShieldAlert className="h-4 w-4" />
            <span>{verifying}</span>
          </div>
        ) : null}

        {failedDetail ? (
          <div className="stateBox danger">
            <XCircle className="h-4 w-4" />
            <span>{failedDetail}</span>
          </div>
        ) : null}

        <div className="formActions justify-end">
          <button className="btn-secondary" type="button" onClick={handleClose}>
            取消
          </button>
          <button className="btn-primary" type="button" onClick={refreshQr} disabled={beginLogin.isPending}>
            {beginLogin.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span>重新获取二维码</span>
          </button>
        </div>
      </div>
    </Modal>
  );
}
