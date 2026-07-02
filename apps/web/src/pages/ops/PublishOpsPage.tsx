import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  Edit3,
  Loader2,
  LogIn,
  Plus,
  QrCode,
  RadioTower,
  RefreshCw,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  api,
  type CreateClientRequest,
  type CreatePublishAccountRequest,
  type PatchPublishAccountRequest,
  type PublishAccount,
  type PublishClient,
  type PublishPlatform,
  type PublishLoginState,
} from "../../api/client";
import { QrLoginDialog } from "../../components/publish/QrLoginDialog";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Modal } from "../../components/ui/Modal";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/State";
import { useToast } from "../../components/ui/Toast";

const platformOptions: Array<{ value: PublishPlatform; label: string }> = [
  { value: "douyin", label: "抖音" },
  { value: "shipinhao", label: "视频号" },
  { value: "kuaishou", label: "快手" },
  { value: "xiaohongshu", label: "小红书" },
];

const platformLabels = Object.fromEntries(platformOptions.map((item) => [item.value, item.label])) as Record<
  PublishPlatform,
  string
>;

const loginStateLabels: Record<PublishLoginState, string> = {
  logged_in: "已登录",
  logged_out: "需重新登录",
  unknown: "待小V猫连接",
};

const loginStateBadgeClasses: Record<PublishLoginState, string> = {
  logged_in: "bg-status-success/15 text-status-success",
  logged_out: "bg-status-error/15 text-status-error",
  unknown: "bg-black/5 text-text-tertiary",
};

function compareNullable(a?: string | null, b?: string | null) {
  return (a ?? "").localeCompare(b ?? "", "zh-CN");
}

function PlatformBadge({ platform }: { platform: PublishPlatform }) {
  return (
    <span className="inline-flex items-center rounded-full bg-status-info/12 px-2.5 py-1 text-xs font-medium text-status-info">
      {platformLabels[platform]}
    </span>
  );
}

function LoginStateBadge({ state }: { state: PublishLoginState }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${loginStateBadgeClasses[state]}`}>
      {loginStateLabels[state]}
    </span>
  );
}

function HealthTile({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: number;
  detail?: string;
  tone?: "success" | "danger" | "neutral";
}) {
  const toneClass =
    tone === "success"
      ? "border-status-success/25 bg-status-success/10 text-status-success"
      : tone === "danger"
        ? "border-status-error/30 bg-status-error/10 text-status-error"
        : "border-border/70 bg-white/65 text-text-primary";
  return (
    <div className={`rounded-2xl border p-4 ${toneClass}`}>
      <p className="text-xs font-semibold opacity-75">{label}</p>
      <p className="mt-2 font-mono text-3xl font-semibold tabular-nums">{value}</p>
      {detail ? <p className="mt-1 text-xs opacity-75">{detail}</p> : null}
    </div>
  );
}

function loginStateHint(account: PublishAccount) {
  if (account.login_state === "unknown") return "登录态待小V猫连接";
  return "登录态实时来自小V猫";
}

export default function PublishOpsPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [selectedClientId, setSelectedClientId] = useState("");
  const [selectedPlatform, setSelectedPlatform] = useState<PublishPlatform | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [clientDialogOpen, setClientDialogOpen] = useState(false);
  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<PublishAccount | null>(null);
  const [archiveAccount, setArchiveAccount] = useState<PublishAccount | null>(null);
  const [loginAccount, setLoginAccount] = useState<PublishAccount | null>(null);

  const clientsQuery = useQuery({
    queryKey: ["publish-clients"],
    queryFn: () => api.publishOps.listClients({ limit: 200, include_archived: true }),
  });

  const accountFilters = useMemo(
    () => ({
      client_id: selectedClientId || undefined,
      platform: selectedPlatform || undefined,
      include_archived: includeArchived,
    }),
    [includeArchived, selectedClientId, selectedPlatform],
  );

  const accountsQuery = useQuery({
    queryKey: ["publish-accounts", accountFilters],
    queryFn: () => api.publishOps.listAccounts({ ...accountFilters, limit: 300 }),
  });

  const clients = useMemo(() => clientsQuery.data?.items ?? [], [clientsQuery.data?.items]);
  const clientOptions = useMemo(
    () => clients.filter((client) => includeArchived || client.status !== "archived"),
    [clients, includeArchived],
  );
  const activeClients = useMemo(() => clients.filter((client) => client.status !== "archived"), [clients]);
  const clientById = useMemo(() => {
    const lookup = new Map<string, PublishClient>();
    clients.forEach((client) => lookup.set(client.id, client));
    return lookup;
  }, [clients]);

  useEffect(() => {
    if (selectedClientId && !clientOptions.some((client) => client.id === selectedClientId)) {
      setSelectedClientId("");
    }
  }, [clientOptions, selectedClientId]);

  const accountRows = useMemo(() => {
    const rows = [...(accountsQuery.data?.items ?? [])];
    rows.sort((left, right) => {
      const clientCompare = compareNullable(clientById.get(left.client_id)?.name, clientById.get(right.client_id)?.name);
      if (clientCompare !== 0) return clientCompare;
      const platformCompare = platformLabels[left.platform].localeCompare(platformLabels[right.platform], "zh-CN");
      if (platformCompare !== 0) return platformCompare;
      return left.account_name.localeCompare(right.account_name, "zh-CN");
    });
    return rows;
  }, [accountsQuery.data?.items, clientById]);

  const loginCounts = useMemo(() => {
    const counts: Record<PublishLoginState, number> = {
      logged_in: 0,
      logged_out: 0,
      unknown: 0,
    };
    accountRows.forEach((account) => {
      counts[account.login_state] += 1;
    });
    return counts;
  }, [accountRows]);

  const invalidateClients = async () => {
    await queryClient.invalidateQueries({ queryKey: ["publish-clients"] });
  };

  const invalidateAccounts = async () => {
    await queryClient.invalidateQueries({ queryKey: ["publish-accounts"] });
  };

  const createClient = useMutation({
    mutationFn: (body: CreateClientRequest) => api.publishOps.createClient(body),
    onSuccess: async (client) => {
      setClientDialogOpen(false);
      toast.success("客户已创建", client.name);
      await invalidateClients();
    },
    onError: (error) => toast.error("客户创建失败", error),
  });

  const createAccount = useMutation({
    mutationFn: (body: CreatePublishAccountRequest) => api.publishOps.createAccount(body),
    onSuccess: async (account) => {
      setAccountDialogOpen(false);
      toast.success("账号已创建", account.account_name);
      await invalidateAccounts();
    },
    onError: (error) => toast.error("账号创建失败", error),
  });

  const patchAccount = useMutation({
    mutationFn: ({ accountId, body }: { accountId: string; body: PatchPublishAccountRequest }) =>
      api.publishOps.patchAccount(accountId, body),
    onSuccess: async (account) => {
      setEditingAccount(null);
      toast.success("账号已更新", account.account_name);
      await invalidateAccounts();
    },
    onError: (error) => toast.error("账号更新失败", error),
  });

  const archiveMutation = useMutation({
    mutationFn: (account: PublishAccount) => api.publishOps.deleteAccount(account.id),
    onSuccess: async (_response, account) => {
      setArchiveAccount(null);
      toast.success("账号已归档", account.account_name);
      await invalidateAccounts();
    },
    onError: (error) => toast.error("归档失败", error),
  });

  const validateSession = useMutation({
    mutationFn: (account: PublishAccount) => api.publishOps.validateSession(account.id),
    onSuccess: async (response) => {
      toast.success("登录态已校验", loginStateLabels[response.login_state]);
      await invalidateAccounts();
    },
    onError: (error) => toast.error("会话校验失败", error),
  });

  const loading = clientsQuery.isLoading || accountsQuery.isLoading;
  const queryError = clientsQuery.error || accountsQuery.error;
  const canCreateAccount = activeClients.length > 0;
  const defaultClientId =
    selectedClientId && activeClients.some((client) => client.id === selectedClientId)
      ? selectedClientId
      : (activeClients[0]?.id ?? "");

  function primaryAction(account: PublishAccount) {
    if (account.login_state === "logged_in") {
      validateSession.mutate(account);
    } else {
      setLoginAccount(account);
    }
  }

  function primaryActionMeta(account: PublishAccount) {
    if (account.login_state === "logged_in") {
      return { label: "校验", icon: CheckCircle2, className: "btn-secondary compactButton" };
    }
    if (account.login_state === "logged_out") {
      return { label: "重新登录", icon: RefreshCw, className: "btn-danger compactButton" };
    }
    return { label: "登录", icon: LogIn, className: "btn-secondary compactButton" };
  }

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>发布运维</h1>
          <p className="mt-2 text-sm text-text-secondary">
            统一管理所有客户的发布账号与登录会话，失效账号可后台连接小V猫扫码重新登录。
          </p>
        </div>
      </header>

      <section className={`card grid gap-4 p-5 ${loginCounts.logged_out > 0 ? "border-status-error/35" : ""}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <RadioTower className="h-5 w-5 text-accent" />
            <h2 className="text-lg font-semibold text-text-primary">登录健康</h2>
            <span className="text-xs text-text-tertiary">登录态实时来自小V猫，登录会自动尝试后台连接</span>
          </div>
          {loginCounts.logged_out > 0 ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-status-error/10 px-3 py-1 text-sm font-medium text-status-error">
              <AlertTriangle className="h-4 w-4" />
              {loginCounts.logged_out} 个账号需要重新登录
            </span>
          ) : null}
        </div>
        <div className="grid gap-3 md:grid-cols-5">
          <HealthTile label="客户数" value={clientOptions.length} detail={includeArchived ? "含已归档客户" : "活跃客户"} />
          <HealthTile label="账号数" value={accountRows.length} detail={includeArchived ? "含已归档账号" : "活跃账号"} />
          <HealthTile label="已登录" value={loginCounts.logged_in} tone="success" />
          <HealthTile label="需重登" value={loginCounts.logged_out} tone={loginCounts.logged_out > 0 ? "danger" : "neutral"} />
          <HealthTile label="待小V猫" value={loginCounts.unknown} />
        </div>
      </section>

      <section className="card grid gap-4 p-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(180px,260px)_minmax(160px,220px)_auto_1fr] lg:items-end">
          <label className="grid gap-1.5">
            <span>客户</span>
            <select value={selectedClientId} onChange={(event) => setSelectedClientId(event.target.value)}>
              <option value="">全部客户</option>
              {clientOptions.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.name}
                  {client.status === "archived" ? "（已归档）" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1.5">
            <span>平台</span>
            <select
              value={selectedPlatform}
              onChange={(event) => setSelectedPlatform(event.target.value as PublishPlatform | "")}
            >
              <option value="">全部平台</option>
              {platformOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-h-10 items-center gap-2 rounded-2xl border border-border/70 bg-white/65 px-3 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => setIncludeArchived(event.target.checked)}
            />
            <span>含已归档</span>
          </label>
          <div className="flex flex-wrap justify-start gap-2 lg:justify-end">
            <button className="btn-secondary" type="button" onClick={() => setClientDialogOpen(true)}>
              <Plus className="h-4 w-4" />
              <span>新建客户</span>
            </button>
            <button
              className="btn-primary"
              type="button"
              onClick={() => setAccountDialogOpen(true)}
              disabled={!canCreateAccount}
              title={canCreateAccount ? undefined : "请先创建活跃客户"}
            >
              <Plus className="h-4 w-4" />
              <span>新建账号</span>
            </button>
          </div>
        </div>
      </section>

      {loading ? <LoadingState block label="正在加载发布账号" /> : null}
      {queryError ? <ErrorState error={queryError} /> : null}

      {!loading && !queryError ? (
        <section className="dataTable">
          <div className="tableRow tableHead hidden lg:grid lg:grid-cols-[1.1fr_0.75fr_1.25fr_1.25fr_1.45fr]">
            <span>客户</span>
            <span>平台</span>
            <span>账号</span>
            <span>会话状态</span>
            <span>操作</span>
          </div>
          {accountRows.map((account) => {
            const client = clientById.get(account.client_id);
            const action = primaryActionMeta(account);
            const ActionIcon = action.icon;
            return (
              <div
                className="tableRow grid-cols-1 lg:grid-cols-[1.1fr_0.75fr_1.25fr_1.25fr_1.45fr]"
                key={account.id}
              >
                <div>
                  <span className="mb-1 block text-xs font-semibold text-text-tertiary lg:hidden">客户</span>
                  <p className="truncate text-sm font-semibold text-text-primary">{client?.name ?? account.client_id}</p>
                  {client?.remark ? <p className="mt-0.5 truncate text-xs text-text-tertiary">{client.remark}</p> : null}
                </div>
                <div>
                  <span className="mb-1 block text-xs font-semibold text-text-tertiary lg:hidden">平台</span>
                  <PlatformBadge platform={account.platform} />
                </div>
                <div>
                  <span className="mb-1 block text-xs font-semibold text-text-tertiary lg:hidden">账号</span>
                  <p className="truncate text-sm font-semibold text-text-primary">{account.account_name}</p>
                  <p className="mt-0.5 truncate font-mono text-xs text-text-tertiary">
                    {account.platform_uid || "未填写 platform_uid"}
                  </p>
                  {account.status === "archived" ? (
                    <span className="mt-1 inline-flex rounded-full bg-black/5 px-2 py-0.5 text-[11px] text-text-tertiary">
                      已归档
                    </span>
                  ) : null}
                </div>
                <div>
                  <span className="mb-1 block text-xs font-semibold text-text-tertiary lg:hidden">登录状态</span>
                  <LoginStateBadge state={account.login_state} />
                  <p className="mt-1 text-xs text-text-tertiary">{loginStateHint(account)}</p>
                </div>
                <div className="rowActions">
                  <button
                    className={action.className}
                    type="button"
                    onClick={() => primaryAction(account)}
                    disabled={validateSession.isPending || account.status === "archived"}
                  >
                    {validateSession.isPending && account.login_state === "logged_in" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ActionIcon className="h-4 w-4" />
                    )}
                    <span>{action.label}</span>
                  </button>
                  <button className="btn-secondary compactButton" type="button" onClick={() => setEditingAccount(account)}>
                    <Edit3 className="h-4 w-4" />
                    <span>编辑</span>
                  </button>
                  {account.status === "archived" ? (
                    <button className="btn-secondary compactButton" type="button" disabled>
                      <Archive className="h-4 w-4" />
                      <span>已归档</span>
                    </button>
                  ) : (
                    <button
                      className="btn-secondary compactButton dangerButton"
                      type="button"
                      onClick={() => setArchiveAccount(account)}
                    >
                      <Archive className="h-4 w-4" />
                      <span>归档</span>
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {accountRows.length === 0 ? (
            <div className="p-4">
              {clients.length === 0 ? (
                <EmptyState
                  title="暂无客户"
                  detail="先创建客户，再为客户添加发布账号。"
                  icon={Users}
                  action={
                    <button className="btn-primary" type="button" onClick={() => setClientDialogOpen(true)}>
                      <Plus className="h-4 w-4" />
                      <span>新建客户</span>
                    </button>
                  }
                />
              ) : (
                <EmptyState
                  title="暂无发布账号"
                  detail="当前筛选下没有账号，可新建账号或调整筛选条件。"
                  icon={QrCode}
                  action={
                    <button
                      className="btn-primary"
                      type="button"
                      onClick={() => setAccountDialogOpen(true)}
                      disabled={!canCreateAccount}
                    >
                      <Plus className="h-4 w-4" />
                      <span>新建账号</span>
                    </button>
                  }
                />
              )}
            </div>
          ) : null}
        </section>
      ) : null}

      {clientDialogOpen ? (
        <ClientDialog
          isPending={createClient.isPending}
          onClose={() => setClientDialogOpen(false)}
          onSubmit={(body) => createClient.mutate(body)}
        />
      ) : null}

      {accountDialogOpen ? (
        <AccountDialog
          clients={activeClients}
          defaultClientId={defaultClientId}
          isPending={createAccount.isPending}
          onClose={() => setAccountDialogOpen(false)}
          onSubmitCreate={(body) => createAccount.mutate(body)}
        />
      ) : null}

      {editingAccount ? (
        <AccountDialog
          account={editingAccount}
          clients={clients}
          defaultClientId={editingAccount.client_id}
          isPending={patchAccount.isPending}
          onClose={() => setEditingAccount(null)}
          onSubmitPatch={(body) => patchAccount.mutate({ accountId: editingAccount.id, body })}
        />
      ) : null}

      {loginAccount ? (
        <QrLoginDialog
          account={loginAccount}
          onClose={() => setLoginAccount(null)}
          onSuccess={() => {
            void invalidateAccounts();
          }}
        />
      ) : null}

      <ConfirmDialog
        isOpen={Boolean(archiveAccount)}
        onClose={() => setArchiveAccount(null)}
        onConfirm={() => {
          if (archiveAccount) archiveMutation.mutate(archiveAccount);
        }}
        title="归档发布账号"
        message={archiveAccount ? `确定归档「${archiveAccount.account_name}」吗？` : ""}
        consequences={["归档后默认筛选中不再展示该账号。", "登录会话会被清除，相关 case 发布目标会被解绑。"]}
        confirmText="归档"
        type="danger"
        isLoading={archiveMutation.isPending}
      />
    </section>
  );
}

function ClientDialog({
  isPending,
  onClose,
  onSubmit,
}: {
  isPending: boolean;
  onClose: () => void;
  onSubmit: (body: CreateClientRequest) => void;
}) {
  const [name, setName] = useState("");
  const [remark, setRemark] = useState("");
  const disabled = isPending || !name.trim();

  return (
    <Modal isOpen onClose={onClose} title="新建客户" size="md">
      <form
        className="formGrid"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit({ name: name.trim(), remark: remark.trim() });
        }}
      >
        <label className="grid gap-1.5">
          <span>客户名称</span>
          <input value={name} onChange={(event) => setName(event.target.value)} required autoFocus />
        </label>
        <label className="grid gap-1.5">
          <span>备注</span>
          <textarea
            className="min-h-[96px]"
            value={remark}
            onChange={(event) => setRemark(event.target.value)}
            placeholder="可填写客户品牌、账号归属或运营备注"
          />
        </label>
        <div className="formActions justify-end">
          <button className="btn-secondary" type="button" onClick={onClose} disabled={isPending}>
            取消
          </button>
          <button className="btn-primary" type="submit" disabled={disabled}>
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            <span>创建</span>
          </button>
        </div>
      </form>
    </Modal>
  );
}

function AccountDialog({
  account,
  clients,
  defaultClientId,
  isPending,
  onClose,
  onSubmitCreate,
  onSubmitPatch,
}: {
  account?: PublishAccount;
  clients: PublishClient[];
  defaultClientId: string;
  isPending: boolean;
  onClose: () => void;
  onSubmitCreate?: (body: CreatePublishAccountRequest) => void;
  onSubmitPatch?: (body: PatchPublishAccountRequest) => void;
}) {
  const [clientId, setClientId] = useState(defaultClientId);
  const [platform, setPlatform] = useState<PublishPlatform | "">(account?.platform ?? "douyin");
  const [accountName, setAccountName] = useState(account?.account_name ?? "");
  const [platformUid, setPlatformUid] = useState(account?.platform_uid ?? "");
  const clientName = clients.find((client) => client.id === (account?.client_id ?? clientId))?.name ?? account?.client_id;
  const disabled = isPending || !accountName.trim() || (!account && (!clientId || !platform));

  return (
    <Modal isOpen onClose={onClose} title={account ? "编辑账号" : "新建账号"} size="md">
      <form
        className="formGrid"
        onSubmit={(event) => {
          event.preventDefault();
          if (account) {
            onSubmitPatch?.({
              account_name: accountName.trim(),
              platform_uid: platformUid.trim() || null,
            });
            return;
          }
          if (!platform) return;
          onSubmitCreate?.({
            client_id: clientId,
            platform,
            account_name: accountName.trim(),
            platform_uid: platformUid.trim() || null,
          });
        }}
      >
        {account ? (
          <div className="stateBox muted">
            <RadioTower className="h-4 w-4" />
            <span>
              {clientName} · {platformLabels[account.platform]}
            </span>
          </div>
        ) : (
          <div className="twoCol">
            <label className="grid gap-1.5">
              <span>客户</span>
              <select value={clientId} onChange={(event) => setClientId(event.target.value)} required>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5">
              <span>平台</span>
              <select
                value={platform}
                onChange={(event) => setPlatform(event.target.value as PublishPlatform)}
                required
              >
                {platformOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        <label className="grid gap-1.5">
          <span>账号名称</span>
          <input value={accountName} onChange={(event) => setAccountName(event.target.value)} required autoFocus />
        </label>
        <label className="grid gap-1.5">
          <span>platform_uid</span>
          <input
            value={platformUid}
            onChange={(event) => setPlatformUid(event.target.value)}
            placeholder="可选，平台侧账号标识"
          />
        </label>
        <div className="formActions justify-end">
          <button className="btn-secondary" type="button" onClick={onClose} disabled={isPending}>
            取消
          </button>
          <button className="btn-primary" type="submit" disabled={disabled}>
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            <span>{account ? "保存" : "创建"}</span>
          </button>
        </div>
      </form>
    </Modal>
  );
}
