export const meta = {
  name: 'repo-cleanup',
  description: '保守清理：死代码/AI slop/过度防御 —— 分析器播种 + agent 阅读 + 对抗式复核，报告或落地',
  whenToUse: '需要在保守约束下清理仓库的死函数、AI slop、过度防御代码，且要求每条候选经对抗式复核、落地有测试门控时',
  phases: [
    { title: 'Find', detail: '按 area 并行：分析器播种死代码 + agent 阅读找 slop/过度防御' },
    { title: 'Verify', detail: '每条候选独立 skeptic 对抗式复核动态/框架引用，保守降级' },
    { title: 'Report', detail: '汇总确认项/标记项/丢弃项' },
  ],
}

// ---- args ----
// {
//   repoRoot: string,                 // 必填：有 .venv 和 apps/web/node_modules 的 checkout 绝对路径
//   mode?: 'report' | 'apply',        // 默认 report（只产候选，不改代码）
//   areas?: Area[],                   // 可选：覆盖默认 area 划分
//   approvedIds?: string[],           // mode='apply' 时：批准落地的 finding id
//   targetRoot?: string,              // mode='apply' 时：在哪个 checkout 改代码（默认 repoRoot）
//   testCmd?: string,                 // mode='apply' 时测试门控命令（默认 .venv/bin/pytest -q）
// }
const repoRoot = (args && args.repoRoot) || '.'
const mode = (args && args.mode) || 'report'

const DEFAULT_AREAS = [
  { label: 'core-contracts', lang: 'py', paths: ['packages/core/contracts'] },
  { label: 'core-storage', lang: 'py', paths: ['packages/core/storage'] },
  { label: 'core-other', lang: 'py', paths: ['packages/core/observability', 'packages/core/workflow', 'packages/core/auth'] },
  { label: 'ai', lang: 'py', paths: ['packages/ai'] },
  { label: 'production', lang: 'py', paths: ['packages/production'] },
  { label: 'media', lang: 'py', paths: ['packages/media'] },
  { label: 'creative', lang: 'py', paths: ['packages/creative', 'packages/planning'] },
  { label: 'ops-publishing', lang: 'py', paths: ['packages/ops', 'packages/publishing'] },
  { label: 'migrations', lang: 'py', paths: ['packages/migrations'] },
  { label: 'api-routers', lang: 'py', paths: ['apps/api/routers'] },
  { label: 'api-services', lang: 'py', paths: ['apps/api/services', 'apps/api'] },
  { label: 'worker', lang: 'py', paths: ['apps/worker'] },
  { label: 'web', lang: 'ts', paths: ['apps/web/src'] },
]
const AREAS = (args && args.areas) || DEFAULT_AREAS

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['area', 'findings'],
  properties: {
    area: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['id', 'category', 'file', 'lines', 'kind', 'evidence', 'confidence', 'test_covered', 'suggested_change'],
        properties: {
          id: { type: 'string', description: 'area-序号，如 ai-1' },
          category: { type: 'string', enum: ['dead', 'slop', 'defense'] },
          file: { type: 'string', description: '相对仓库根路径' },
          lines: { type: 'string', description: '起止行，如 "120-135" 或 "88"' },
          symbol: { type: 'string', description: '函数/类/导出名，无则空串' },
          kind: { type: 'string', description: '如 unused function / 复述式注释 / 吞异常' },
          evidence: { type: 'string', description: '为何看起来可删/可简化' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
          test_covered: { type: 'boolean', description: 'defense 类必填：该路径是否有测试覆盖' },
          suggested_change: { type: 'string', description: '简洁的改动描述（删什么/简化成什么）' },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['id', 'final_recommendation', 'residual_risk', 'refutation', 'checks_run'],
  properties: {
    id: { type: 'string' },
    final_recommendation: { type: 'string', enum: ['remove', 'flag-only', 'keep'] },
    residual_risk: { type: 'string', enum: ['none', 'low', 'medium', 'high'] },
    refutation: { type: 'string', description: '能反驳"可删/可简化"的最强理由；无则 "none found"' },
    checks_run: { type: 'array', items: { type: 'string' }, description: '实际执行的检查项' },
  },
}

function finderPrompt(area) {
  const paths = area.paths.map((p) => `${repoRoot}/${p}`).join(' ')
  const common = `你在保守清理一个数字人内容生产系统的仓库。仓库根（含 .venv 与 apps/web/node_modules）：${repoRoot}
本次负责 area「${area.label}」，范围：${area.paths.join(', ')}。
所有命令用绝对路径在 ${repoRoot} 下跑；输出 file 字段用**相对仓库根**的路径。

要找三类候选（保守，宁缺毋滥）：
1) dead（死代码）：0 引用且无动态/框架引用的函数/方法/类/导出/未用导入。
2) slop（AI slop）：复述代码的废话注释、无信息量的样板 docstring、被注释掉的死代码块、纯模板化冗余。**只标删了不改变任何行为的**。
3) defense（过度防御）：吞异常（except: pass / 宽泛 except 吞掉后继续）、永不触发的 guard、重复校验、belt-and-suspenders。**只在删除安全、且该路径有测试覆盖时**才标记；test_covered 必须如实填。

判定权不在你——你只负责**发现并给证据**，下游有独立 skeptic 复核。但置信度要诚实：拿不准填 low。
已知假阳性（不要当 dead 报）：Pydantic 模型字段、Enum 成员、FastAPI 路由 handler、Temporal @activity/@workflow、Alembic upgrade/downgrade、SQLAlchemy 钩子(如 get_col_spec)、__all__ 再导出、pytest fixture/conftest、被前端调用的 API 契约。`

  if (area.lang === 'py') {
    return `${common}

执行步骤：
1. 跑 \`${repoRoot}/.venv/bin/vulture ${paths} --min-confidence 60\`，只取 "unused function/method/class/import"（忽略 "unused variable"——多为 Pydantic 字段）。
2. 跑 \`${repoRoot}/.venv/bin/ruff check ${paths} --select F401,F811,F841 --output-format concise\`。
3. Read 这些命中文件，确认上下文；同时通读这些文件找 slop 与 defense 候选。
4. 对每个 dead 候选，先用 \`grep -rn "<symbol>" ${repoRoot}/packages ${repoRoot}/apps ${repoRoot}/tests\` 粗查引用，0 引用才报、并把引用计数写进 evidence。
返回 area「${area.label}」的结构化 findings（无候选则 findings 为空数组）。id 用 "${area.label}-N"。`
  }
  // ts
  return `${common}

执行步骤：
1. 跑 \`cd ${repoRoot}/apps/web && npx --yes knip --no-progress\`，取 Unused files / Unused exports / Unused exported types / Unused dependencies。
2. Read 命中文件确认；注意 src/contracts/*.typecheck.ts 是**编译期类型断言文件**（故意 unused），通常应 keep 或 flag-only，不要当死代码删。
3. 注意重复组件（如 components/Toast.tsx 与 components/ui/Toast.tsx 并存）——找出哪个是死副本。
4. 通读命中文件找 TS 侧 slop 与 defense 候选。
5. 对每个 unused export，用 \`grep -rn "<symbol>" ${repoRoot}/apps/web/src\` 复查 0 引用。
返回 area「${area.label}」结构化 findings。id 用 "${area.label}-N"。`
}

function verifyPrompt(f) {
  return `你是对抗式复核 skeptic，任务是**尽力反驳**下面这条清理候选"可删/可简化"。保守原则：只要有合理怀疑就降级，拿不准就别让它过。仓库根：${repoRoot}（用绝对路径跑命令）。

候选：
- id: ${f.id}
- 类别: ${f.category}
- 文件: ${f.file}  行: ${f.lines}  符号: ${f.symbol || '(无)'}
- kind: ${f.kind}
- 证据: ${f.evidence}
- 建议改动: ${f.suggested_change}
- 自报测试覆盖(defense): ${f.test_covered}

必须实际执行的检查（按类别）：
- dead：grep 符号在 ${repoRoot} 全仓的引用，含动态引用（getattr/globals/字符串/importlib/__all__ 再导出）、框架注册（FastAPI 路由、Temporal @activity/@workflow、Alembic 版本、Pydantic/SQLAlchemy 事件、pytest fixture/conftest、entry_points/setuptools）、对外面（HTTP route / CLI / 被测试或前端引用）。
- slop：Read 上下文确认删除后**行为零变化**（注释/docstring/死注释块才算 slop；若"注释"其实是 type: ignore、pragma、noqa、编译指令、许可证头则不可删）。
- defense：Read 该处与对应测试，确认①去掉 guard/except 后真的安全、②该路径**确有测试覆盖**。两者缺一即不可简化。

输出 final_recommendation：
- remove：经检查确认安全可删/可简化，residual_risk=none/low。
- flag-only：有疑点或属语义判断，建议人工确认后再动。
- keep：找到确凿反驳（有引用/框架注册/无测试覆盖），不应动。
refutation 写你找到的最强反驳理由（没有则 "none found"），checks_run 列实际跑过的检查。`
}

// ---- Find + Verify pipeline（按 area 流水线，verify 随各 area 完成即跑）----
phase('Find')
const perArea = await pipeline(
  AREAS,
  (area) => agent(finderPrompt(area), { label: `find:${area.label}`, phase: 'Find', schema: FINDINGS_SCHEMA }),
  (found, area) => {
    if (!found || !found.findings || found.findings.length === 0) return { area: area.label, items: [] }
    return parallel(
      found.findings.map((f) => () =>
        agent(verifyPrompt(f), { label: `verify:${f.id}`, phase: 'Verify', schema: VERDICT_SCHEMA })
          .then((v) => ({ finding: f, verdict: v || { id: f.id, final_recommendation: 'flag-only', residual_risk: 'medium', refutation: 'skeptic 失败，默认降级', checks_run: [] } }))
      )
    ).then((items) => ({ area: area.label, items: items.filter(Boolean) }))
  }
)

phase('Report')
const all = []
for (const a of perArea) {
  if (!a || !a.items) continue
  for (const it of a.items) all.push({ ...it.finding, area: a.area, verdict: it.verdict })
}
const confirmed = all.filter((f) => f.verdict.final_recommendation === 'remove')
const flagged = all.filter((f) => f.verdict.final_recommendation === 'flag-only')
const dropped = all.filter((f) => f.verdict.final_recommendation === 'keep')
log(`复核完成：候选 ${all.length}，确认可删 ${confirmed.length}，待人工确认 ${flagged.length}，已否决 ${dropped.length}`)

const byCat = (arr, c) => arr.filter((f) => f.category === c)
const result = {
  mode,
  totals: { candidates: all.length, confirmed: confirmed.length, flagged: flagged.length, dropped: dropped.length },
  confirmed: {
    dead: byCat(confirmed, 'dead'),
    slop: byCat(confirmed, 'slop'),
    defense: byCat(confirmed, 'defense'),
  },
  flagged,
  dropped,
}

if (mode !== 'apply') {
  return result
}

// ---- Apply 模式：仅落地 approvedIds 指定的 finding，逐条改 + 测试门控 ----
const targetRoot = (args && args.targetRoot) || repoRoot
const testCmd = (args && args.testCmd) || `${targetRoot}/.venv/bin/pytest -q`
const approvedIds = new Set((args && args.approvedIds) || [])
const toApply = confirmed.dead.concat(confirmed.slop, confirmed.defense).filter((f) => approvedIds.has(f.id))
log(`Apply 模式：批准 ${approvedIds.size} 条，匹配到确认项 ${toApply.length} 条`)

phase('Apply')
const applied = await parallel(
  toApply.map((f) => () =>
    agent(
      `在 ${targetRoot} 落地这条已批准的清理（最小改动，不顺带改其他东西）：
文件 ${f.file} 行 ${f.lines} 符号 ${f.symbol || ''}
改动：${f.suggested_change}
用 Read 看现状、Edit 精确改。改完返回简短 diff 摘要。`,
      { label: `apply:${f.id}`, phase: 'Apply' }
    ).then((s) => ({ id: f.id, file: f.file, summary: s }))
  )
)
const gate = await agent(
  `运行测试门控：\`${testCmd}\`。只返回是否全绿（pass/fail）、失败用例名、关键错误行。`,
  { label: 'gate:pytest', phase: 'Apply' }
)
return { mode, applied: applied.filter(Boolean), gate, appliedCount: applied.filter(Boolean).length }
