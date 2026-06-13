export const meta = {
  name: 'slop-defense-sweep',
  description: '激进清扫 AI slop + 过度防御：agent 读码找候选 + 独立 skeptic 复核，返回带精确片段的计划',
  phases: [
    { title: 'Find', detail: '按 area 并行读码，找 slop 与过度防御候选' },
    { title: 'Verify', detail: '每条独立 skeptic 复核：slop 须行为中立；defense 须安全+有测试覆盖' },
  ],
}

const repoRoot = (args && args.repoRoot) || '.'
const AREAS = (args && args.areas) || [
  { label: 'core-contracts', paths: ['packages/core/contracts'] },
  { label: 'core-storage', paths: ['packages/core/storage'] },
  { label: 'core-workflow', paths: ['packages/core/workflow', 'packages/core/observability', 'packages/core/auth'] },
  { label: 'ai', paths: ['packages/ai'] },
  { label: 'production', paths: ['packages/production'] },
  { label: 'media', paths: ['packages/media'] },
  { label: 'creative-planning', paths: ['packages/creative', 'packages/planning'] },
  { label: 'ops-publishing-migrations', paths: ['packages/ops', 'packages/publishing', 'packages/migrations'] },
  { label: 'api-routers', paths: ['apps/api/routers'] },
  { label: 'api-services', paths: ['apps/api/services', 'apps/api'] },
  { label: 'worker', paths: ['apps/worker'] },
  { label: 'web', paths: ['apps/web/src'] },
]

const FIND_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['area', 'findings'],
  properties: {
    area: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['id', 'category', 'file', 'line_start', 'line_end', 'exact_snippet', 'replacement', 'rationale', 'behavior_neutral', 'test_covered'],
        properties: {
          id: { type: 'string' },
          category: { type: 'string', enum: ['slop', 'defense'] },
          file: { type: 'string', description: '相对仓库根' },
          line_start: { type: 'integer' },
          line_end: { type: 'integer' },
          exact_snippet: { type: 'string', description: '要替换/删除的当前原文，逐字节照抄（含缩进），用作 old_string' },
          replacement: { type: 'string', description: '替换为的新文本；纯删除则空串' },
          rationale: { type: 'string' },
          behavior_neutral: { type: 'boolean', description: 'slop 必须 true' },
          test_covered: { type: 'boolean', description: 'defense 简化点是否有测试覆盖该路径' },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['id', 'approve', 'reason'],
  properties: {
    id: { type: 'string' },
    approve: { type: 'boolean', description: '是否批准应用' },
    reason: { type: 'string' },
    snippet_verified: { type: 'boolean', description: 'exact_snippet 是否与文件当前内容逐字节一致' },
  },
}

function findPrompt(area) {
  return `你在**激进**清扫一个数字人生产系统仓库的 AI slop 与过度防御代码。仓库根：${repoRoot}（用绝对路径 grep/Read）。负责 area「${area.label}」：${area.paths.join(', ')}。

找两类候选：
A) **slop**（AI 生成的废话，删/改后行为零变化）：
   - 复述紧邻代码的废话注释（如 \`# increment counter\` 配 \`counter += 1\`）、无信息量的样板 docstring、被注释掉的死代码块、冗余的类型复述注释。
   - 纯透传包装函数（function 体只是调另一个函数、无附加逻辑）+ 其重复注释。
   - 不可碰：\`# type: ignore\`/\`# noqa\`/\`# pragma\`/编译指令/许可证头/解释"为什么"的有价值注释/TS 的 \`satisfies\` 断言。
B) **defense**（过度防御，删/简化后行为不变且**该路径有测试覆盖**）：
   - 吞异常：\`except Exception: pass\` 或宽泛 except 吞掉后照常继续；
   - 永不触发的 guard、不可达分支、重复校验（同一条件校验两遍）、belt-and-suspenders（已有上游保证还重复兜底）。
   - 仅在**删除安全且有测试覆盖**时报，test_covered 如实填；拿不准不报。

对每条候选：用 Read 看准确行，**exact_snippet 必须逐字节照抄文件当前原文（含前导空格缩进）**，这会被用作精确替换的 old_string；replacement 写替换后文本（纯删除则空串，注意保留周围结构正确）。behavior_neutral：slop 必为 true。
保守边界：宁缺毋滥，只报你高度确信的。返回 area「${area.label}」结构化 findings。id 用「${area.label}-N」。`
}

function verifyPrompt(f) {
  return `对抗复核一条清理候选，仓库根 ${repoRoot}。**尽力找理由否决**，宁可放过不可误删。

- id ${f.id} / 类别 ${f.category}
- 文件 ${f.file} 行 ${f.line_start}-${f.line_end}
- 拟替换原文(exact_snippet):
<<<
${f.exact_snippet}
>>>
- 替换为(replacement，空=纯删):
<<<
${f.replacement}
>>>
- 理由：${f.rationale}  behavior_neutral=${f.behavior_neutral} test_covered=${f.test_covered}

必做：
1. Read ${f.file} 对应行，确认 exact_snippet 与**当前文件逐字节一致**（不一致 → approve=false, snippet_verified=false）。
2. slop：确认删/改后**行为零变化**（注释/docstring/死注释/纯透传；若"注释"其实是指令/noqa/satisfies 断言 → 否决）。
3. defense：确认①去掉后真安全（无边界回归）、②该路径**确有测试覆盖**；两者缺一否决。
4. 替换后语法/缩进正确、不破坏周围结构。
有任何疑点 approve=false。返回 verdict。`
}

phase('Find')
const perArea = await pipeline(
  AREAS,
  (area) => agent(findPrompt(area), { label: `find:${area.label}`, phase: 'Find', schema: FIND_SCHEMA }),
  (found, area) => {
    if (!found || !found.findings || found.findings.length === 0) return []
    return parallel(found.findings.map((f) => () =>
      agent(verifyPrompt(f), { label: `verify:${f.id}`, phase: 'Verify', schema: VERDICT_SCHEMA })
        .then((v) => ({ ...f, area: area.label, verdict: v || { id: f.id, approve: false, reason: 'skeptic 失败' } }))
    ))
  }
)

phase('Verify')
const all = perArea.flat().filter(Boolean)
const approved = all.filter((f) => f.verdict.approve && f.verdict.snippet_verified !== false)
log(`候选 ${all.length}，批准 ${approved.length}（slop ${approved.filter(f=>f.category==='slop').length} / defense ${approved.filter(f=>f.category==='defense').length}）`)
return {
  totals: { candidates: all.length, approved: approved.length },
  approved,
  rejected: all.filter((f) => !(f.verdict.approve && f.verdict.snippet_verified !== false))
    .map((f) => ({ id: f.id, file: f.file, category: f.category, reason: f.verdict.reason })),
}
