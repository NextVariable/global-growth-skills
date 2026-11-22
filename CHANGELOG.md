# Changes

## 1.0.0-rc.3

- Evidence Engine 2.0：claim 支持逐字片段而不只是整段摘录；新增 Claim–Evidence 映射、支持类型、重复合并、时效分级、证据缺口和 provider 指令注入阻断。
- 逐字匹配与语义支持分离：`support` 只表示文本命中，`semantic_support` 在具名评审前保持 `unverified`；新增 `review` 记录和 `needs_review`/`unsupported_claims` 状态，字符串匹配不再被当作事实已验证。
- 门禁只拦截“陈述外部事实却无 claim”的模型输出；无事实断言的建议不再被强制引用无关来源。包状态新增 `needs_evidence_review`。
- `web-public` 抓取固定到一次解析得到的全局单播地址，使用原主机名完成 TLS 校验，阻断 DNS Rebinding/TOCTOU；不支持代理传输。拒绝私网、重定向、非 HTML 和超限响应。
- 来源失效改为精确依赖：只复核引用该来源的决策与草稿，新增无关来源不再误触发失效。
- 模型陈述外部事实却没有结构化 claim 时失败并提示重试；只给建议或假设时不强制引用。包状态新增 `incomplete_evidence`、`needs_evidence_review` 与 `needs_quality_review`。
- 新增只读 `web-public` Provider，可抓取显式公开 HTTPS 页面/定价页；拒绝私网、重定向、非 HTML 和超限响应。
- GTM Package 增加质量评分卡、事实/假设分离、指标公式/分母/护栏/判定规则和跨阶段一致性检查。
- Codex 上下文按阶段选择 Skill 文档并设 60 KB 预算，回执记录 prompt 与文档字节数。
- 新增 `research-web`、`audit`、`doctor` 命令和 RC3 四行业评测集。本轮未执行真实模型调用，评测只覆盖确定性 fixture/reference。
- 本轮未创建正式 Release；`feat/rc3-research-quality` 需审查后合并。

## 2026-10-28 · 维护修订

锁定五包修复版本并重跑真实下载，新增安装验收版本一致性检查；增加安全反馈与更新说明，以及 GitHub Actions 依赖更新检查。业务方法没有在此维护修订中改变；本地检查不能冒充真实客户效果或新一轮模型验收。提交历史和自动检查用于定位交付版本。

## 2026-10-24 · 首用与工程维护

统一首次使用路径、任务示例与仓库展示；补充文档链接检查与跨平台验证。各次行为测试仍绑定其原运行版本，不因文档更新自动升级验收结论。

## 1.0.0-rc.1

- 可选的五阶段编排，支持独立运行、组合、输入变更后恢复和 SQLite 迁移。
- 新增固定版本 Codex 只读调用、可校验的手工交接、来源检查和模拟审批网关。
- 保存真实 Codex 五阶段合成任务、公开产品配对运行及离线验收。多样本业务评测和真实外部工具接入待完成。


## 1.0.0-rc.2

- 增加公开 GitHub 研究、细来源依赖、逐字引用校验和市场数字复核提示。
- CLI 可准备固定 Skill、执行真实模型、恢复和导出 Markdown 或 JSON GTM Package。
- 增加公开产品真实流程、配对结果和 10 项离线任务基线。发布仍保持 RC。
