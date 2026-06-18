import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, RefreshCw, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type LoginStatusResponse, type PublishPlatform } from "../../api/client";
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

export function QrLoginDialog({ account, onClose, onSuccess }: QrLoginDialogProps) {
  const toast = useToast();
  const [loginId, setLoginId] = useState<string | null>(null);
  const [qrImage, setQrImage] = useState<string | null>(null);
  const [failedDetail, setFailedDetail] = useState<string | null>(null);
  const loginIdRef = useRef<string | null>(null);
  const beginSequenceRef = useRef(0);
  const disposedRef = useRef(false);

  const cancelLogin = useCallback(
    async (targetLoginId: string) => {
      await api.publishOps.cancelLogin(account.id, targetLoginId).catch(() => undefined);
    },
    [account.id],
  );

  const beginLogin = useMutation({
    mutationFn: async (sequence: number) => ({
      response: await api.publishOps.beginLogin(account.id),
      sequence,
    }),
    onSuccess: async ({ response, sequence }) => {
      if (disposedRef.current || sequence !== beginSequenceRef.current) {
        await cancelLogin(response.login_id);
        return;
      }
      loginIdRef.current = response.login_id;
      setLoginId(response.login_id);
      setQrImage(response.qr_image);
      setFailedDetail(null);
    },
    onError: (error, sequence) => {
      if (sequence !== beginSequenceRef.current || disposedRef.current) return;
      loginIdRef.current = null;
      setLoginId(null);
      setQrImage(null);
      toast.error("二维码获取失败", error);
    },
  });
  const { mutate: beginLoginMutate } = beginLogin;

  const pollLogin = useQuery({
    queryKey: ["publish-login", account.id, loginId],
    queryFn: () => api.publishOps.pollLogin(account.id, loginId ?? ""),
    enabled: Boolean(loginId),
    refetchInterval: (query) => {
      const data = query.state.data as LoginStatusResponse | undefined;
      return data?.status === "pending" ? 2000 : false;
    },
  });

  const startLogin = useCallback(() => {
    const sequence = beginSequenceRef.current + 1;
    beginSequenceRef.current = sequence;
    beginLoginMutate(sequence);
  }, [beginLoginMutate]);

  const cancelCurrentLogin = useCallback(
    async (clearState = true) => {
      const currentLoginId = loginIdRef.current;
      beginSequenceRef.current += 1;
      loginIdRef.current = null;
      if (clearState) {
        setLoginId(null);
        setQrImage(null);
      }
      if (currentLoginId) {
        await cancelLogin(currentLoginId);
      }
    },
    [cancelLogin],
  );

  const handleClose = useCallback(() => {
    void cancelCurrentLogin();
    onClose();
  }, [cancelCurrentLogin, onClose]);

  useEffect(() => {
    disposedRef.current = false;
    startLogin();
    return () => {
      disposedRef.current = true;
      void cancelCurrentLogin(false);
    };
  }, [cancelCurrentLogin, startLogin]);

  useEffect(() => {
    const data = pollLogin.data;
    if (!data) return;
    if (data.status === "active") {
      toast.success("登录成功", account.account_name);
      onSuccess();
      handleClose();
    } else if (data.status === "failed") {
      setFailedDetail(data.detail || "二维码已失效，请重新获取。");
    }
  }, [account.account_name, handleClose, onSuccess, pollLogin.data, toast]);

  async function refreshQr() {
    await cancelCurrentLogin();
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
            当前账号请使用 {platformApp}。
          </p>
        </div>

        <div className="grid place-items-center rounded-[24px] border border-border/70 bg-white/80 p-5">
          {beginLogin.isPending && !qrImage ? <LoadingState label="正在获取二维码" /> : null}
          {qrImage ? (
            <img
              src={qrImage}
              alt="登录二维码"
              className="h-64 w-64 rounded-2xl border border-border/70 bg-white object-contain p-3"
            />
          ) : null}
          {!beginLogin.isPending && !qrImage ? (
            <div className="stateBox danger">
              <XCircle className="h-4 w-4" />
              <span>二维码不可用，请重新获取。</span>
            </div>
          ) : null}
        </div>

        {pollLogin.data?.status === "pending" ? (
          <div className="stateBox muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>等待扫码确认</span>
          </div>
        ) : null}

        {failedDetail ? (
          <div className="stateBox danger">
            <XCircle className="h-4 w-4" />
            <span>{failedDetail}</span>
          </div>
        ) : null}
        {pollLogin.error ? (
          <div className="stateBox danger">
            <XCircle className="h-4 w-4" />
            <span>{pollLogin.error instanceof Error ? pollLogin.error.message : "登录状态查询失败"}</span>
          </div>
        ) : null}

        <div className="formActions justify-end">
          <button className="btn-secondary" type="button" onClick={handleClose}>
            取消
          </button>
          <button className="btn-primary" type="button" onClick={refreshQr} disabled={beginLogin.isPending}>
            {beginLogin.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span>{failedDetail ? "重新获取二维码" : "刷新二维码"}</span>
          </button>
        </div>
      </div>
    </Modal>
  );
}
