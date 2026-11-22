# GTM Harness MVP · 审计与架构设计

审计日期：2026-11-22。建议把 Harness 放在合集仓库，作为可选的项目编排与验收层。五个 Skill 保持各自安装、各自调用。首个切片做「战略判断 → 落地页草稿 → 价格或产品能力变化后标记草稿待复核」，验证跨 Skill 交接、最小上下文和安全恢复，再接剩余三个角色。

## 1. 仓库审计

在临时目录克隆六仓公开 main，核对源码、五份 SKILL.md、交接模板、测试和 CI 配置。逐仓运行 `python3 scripts/validate.py`，六套均退出 0。另在公开合集快照运行现有安装器，实际安装全部五个固定版本成功。安装验收、结构测试、历史模型回执和真实业务效果分别记账。六个公开 main 的最新 Actions 运行均成功，head SHA 与表中基线一致。报告新增在本地合集分支（原 HEAD 为 2507fe2），实施前需先基于公开 main 合并此文档。

| 仓库 | 审计的公开 main | 合集实际安装版本 | 已实现和已有记录 |
|---|---|---|---|
| 合集 `global-growth-skills` | `77e71668491750eed755c970e7878d6b162233d6` | — | `catalog.json` 指向五个仓库的完整 SHA。`scripts/install.py` 校验目录、版本及安装单元，实际下载复制。十项安装测试及固定版本与验收记录一致性检查。 |
| 战略 `global-gtm-strategy-skill` | `beb359e0ccf1afb5535ff8d42bc904e682afbc7e` | `b9a3f9d46e68e6959211ac5ebccb4a5bd35ead12` | `research_state.py` 初始化项目账本并检查身份、引用、替换链；维护 state、evidence、claims、decisions；陈旧或被替换的依据目前产生警告。`opportunity_math.py` 计算区间。现有校验器明确返回 `execution_readiness: not_assessed`。 |
| 内容 `global-growth-content-skill` | `d05f6813e46973fc2a10cb64e7e096d55d040958` | `d3d8aa367ace0e9ff27ce7a8a21e3ebd5e28140e` | Skill 提供定位、落地页、内容与修订指导，接收文字或战略账本。`scripts/validate.py` 检查包和测试证据，有独立发布溯源测试。 |
| 发布获客 `global-launch-acquisition-skill` | `b4070afa5d2e6351a1be9d1b5e4eebc3fa0d86cc` | `a5bfa7c3d5a64b61bcb17491ad96a9b34269b96e` | 渠道路由、执行及故障恢复指南和交接模板。仓库校验包、文档及回执哈希。 |
| 销售留存 `global-sales-retention-skill` | `5e62b33cc6581468c07eff352575dbae4d5b45fc` | `7c201004d3aba3896808660e56ba4a74b64322b6` | 需求判断、试点、客户交接及续费指南。仓库校验包、文档与测试回执。 |
| 实验 `global-growth-experiments-skill` | `e873fc413d0b7a1b075271b15db0ff06cd0c7fb5` | `fb1060e4ff5c80dcfb00b2c68099a511b1e5eed4` | 实验执行及复盘指南，`conversion_summary.py` 提供描述性计数、本组区间和差值计算，七项测试。 |

**文档指导的能力。** 发布、销售和实验 Skill 在获得授权并具备工具时指导宿主执行，仓库内没有对应渠道、CRM 或付费连接器。合集的 `handoff-example.md` 和五种 Markdown 模板定义交接习惯，历史 `validation/release-20261028/` 保存合成测试产物和运行限制。它们不能充当跨 Skill 状态机、权限拦截或增长效果测量。

**建议新增的能力。** 六仓没有通用的跨 Skill 机器可读契约、产物依赖索引、持久调度与审批执行边界。战略账本的 v1 是该 Skill 的内部格式，合集 catalog 的 v1 是安装格式。Harness 的契约需单独版本化。

### 按优先级处理

| 优先级 | 发现与代码证据 | 行动 |
|---|---|---|
| P0 | 发布、销售、实验的执行授权写在 `SKILL.md` 和 execution 参考文档中，由宿主解释，无独立强制拦截。超时后指南要求读回，重启后的状态没有共享账本。 | 默认只读、草稿及本地状态写入。模型在 Harness 环境中无外部写工具。用确定性授权判断保护任何将来的外部写入。 |
| P0 | 战略 `research_state.py` 有项目身份和引用校验，`initialize` 逐个写文件，`state.json` 记录下一步，陈旧依据通过 warnings 暴露。其余四种交接以 Markdown 为主。跨阶段无统一状态事务，更新后下游可能仍使用旧版本。 | 最小项目隔离、结构化引用、事务 checkpoint 默认为必需。保存旧版本，依赖变化按引用传播待复核。 |
| P1 | 战略、内容都会接触定位，内容与获客都接触文案，获客和销售都接触客户沟通，获客与实验都可能涉及投放。入口已有职责描述，缺少运行时任务归属。 | 按交付目的路由。市场选择归战略，表达归内容，分发归获客，已识别客户行动归销售，指标和判定归实验。组合任务按依赖排队，简单计算和无关请求不启动 GTM 流程。 |
| P1 | 03–05 的 `scripts/validate.py` 在本地固定版本逐字节相同，合集与战略的隐私扫描也各自维护。工具认为安装完成前会检查 SHA，但安装目录没有由安装器写入的来源收据。 | 首版保持各仓独立校验。Harness 仅读 catalog 并核对明确的本地 Skill 根目录和版本证据，对无证明或内容不符的版本拒绝启动可复现运行。后续再评估同步重复工具。 |
| P1 | 当前公开 main 与固定版本不同。相比本地固定工作树，03–05 的 Skill 包入口有变更。CI 验证包、脚本、历史记录；合集的安装验收相关检查不等于每次 CI 都远程下载。 | 首轮评测以同一批固定 SHA 为基线。真实安装回归和离线评测分别报告。升级固定版本另立变更。 |
| P2 | `install.py` 完成全部下载后逐个复制，复制 I/O 失败可留下部分安装。现有安装器针对自身行为已有检查。 | 保留安装语义，Harness 不自动安装或更新，发现缺包给出明确诊断。安装原子性作为独立问题。 |

## 2. 契约提案

使用 [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)。每种记录用统一信封 `schema_version, kind, project_id, id, revision, created_at, payload`，可选 `supersedes_ref`。新增时由运行时分配 ID、时间和版本。引用为 `{kind,id,revision}`，解析上下文限定同一项目。核心对象禁止未知字段，扩展使用显式命名空间。Schema 负责形状、枚举及类型，日期时间显式启用校验。项目权限、引用存在性、有效期、替换链和合法状态转换由应用层验证。

| 契约 | 核心字段与约束 |
|---|---|
| Project Context | `goal, product, audience, markets, constraints, budget, claims`。市场允许未知。预算的金额、币种、计费周期单独表达。每项 claim 有 `claim_id, kind, text, evidence_refs`，kind 区分用户陈述、观察、推断与假设。未知、已确认无、待核实使用不同值。 |
| Evidence | `source_type, source_locator, observed_at, captured_at, status, confidence_basis, digest`，可选 `valid_until, origin_group, usage_scope`。来源只是资料。记录证据类别、授权和局限，保留同源关系以及更正链。 |
| Decision | `question, outcome, rationale, context_ref, claim_ids, evidence_refs, assumptions, review_triggers`。outcome 可为 accepted、provisional、deferred、rejected。缺关键证据时保留条件决策与补证任务。 |
| Artifact | `artifact_type, relative_path, media_type, sha256, produced_by, input_refs, status`。状态区分 draft、reviewed、stale、retired。产物以内容摘要和确切版本登记，文件保存在项目数据区，公开元数据禁止包含本机绝对路径。审稿状态不授予发布权限。 |
| Task State | `run_id, workflow_version, skill_id, skill_sha, input_refs, input_digest, status, attempt, output_refs, gate_results`，可选 `blocked_reason, error_code, approval_request_id, idempotency_key`。事件和重试沿用 run_id，每次执行有独立 attempt。 |

宿主调用的 TaskInput v1 提供任务目标、技能与固定版本、最小上下文快照、允许交付类型和工具范围。TaskResult v1 返回候选证据、决策、产物和阻塞原因。运行时负责验证和登记，模型不能直接写受信状态。现有 Skill 照常读取 Markdown，Harness 用渲染适配器提供已有交接格式，并要求结构化结果作为附加输出。草稿和提取结果分别留存。

**版本与迁移。** 契约 v1 与 catalog v1、战略账本 v1 各自独立。战略适配器用固定版本的原帮助脚本验证源目录，再按原身份、证据、claim 和 decision ID 映射进新空间。未知字段或人工标注缺失时生成迁移报告，不自动升级证据强度或授权。导入按源快照摘要幂等，源数据保持可重读。后续迁移先在副本执行版本链和引用检查，失败保留原状态，未知新版拒绝加载。Markdown 产物可人工登记为 draft，原则上不反解析旧文案来补造事实。

## 3. MVP 的执行设计

- **Registry 与 Router。** 复用 catalog v1 的解析、版本及路径。角色映射由合集维护，声明式流程包含明确的输入/输出需求。用户显式指定 Skill 时优先采用，歧义时给出选择，缺少依赖时可单独补证或完成可降级草稿。任务去向和依据写入 checkpoint。新版 Skill 或流程配置时保留旧运行所绑定的版本，重新执行需要明确迁移或新 run。
- **宿主适配。** 首选复用现有宿主的模型和工具调用。最早可使用「导出任务 → 现有 Agent 执行 → 导入结果」运行，有离线 fixture adapter 验证确定性逻辑。验证宿主能限制工具权限后再接自动调用。保持调用接口可替换。
- **存储与恢复。** 单项目 SQLite 事务保存记录、版本、状态、审批事件与操作收据。用户指定仓库外目录。文件暂存内容寻址、原子重命名后再事务登记，恢复时只清点孤立暂存；校验存在性与哈希。拒绝逃逸、符号链接和跨项目引用。用行版本比较防止陈旧写回。状态为 `queued → running → succeeded`，另有 `blocked / awaiting_approval / failed / outcome_unknown / cancelled`。重启时恢复同一 run；恢复前重算输入摘要，变化则使旧 gate、审批及受影响的下游产物失效。未知外部结果进入人工核对，不能靠重新提交判断。
- **Evaluation Gates。** 审核顺序是 Schema、项目身份与引用、证据时效与用途、产物完整性、任务特定断言。有引用且 JSON 合法只是通过确定性门槛，面向客户的事实与措辞仍需语义抽检。阻塞输出缺什么及可交付什么。价格或能力变化只影响依赖相应 claim/证据版本的产物，不删除历史。
- **Human Approval。** 由可信宿主身份提交批准、拒绝或撤回事件。请求固定项目、run、动作、账户及目标、精确载荷/产物摘要、预算币种上限、期限和幂等键。变更任一字段需新审批。操作提交前事务检查并记录批准被使用，收据写回前失败时先从供应方只读核对。MVP 可测试批准、拒绝、超时、撤回和未知回执，只接模拟执行器；真实发布、触达和付费连接后再做单独验收。遵循 [MCP 工具及确认约定](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。
- **框架选择。** 用 Python 标准库 SQLite、已维护的 JSON Schema 验证库和现有 Agent 宿主组成首版。LangGraph 提供成熟的 checkpoint 与长期 store，待多流程并发、图分支与部署有实际需求时评估其适配价值。首版由一个进程推进一条可恢复流程。[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

## 4. 逐文件改动和验收顺序

以下是后续实现提案。本轮交付此文件，现有五个 Skills、安装器、CI 及 catalog 保持原样。

| 阶段 | 文件级改动 | 可核验完成标准 |
|---|---|---|
| 1 审计 | 新增 `HARNESS_AUDIT.md`。 | 六仓源码与版本有出处，脚本检查和固定版本安装可复查，已实现能力、指导能力、提案分列。 |
| 2 契约 | 新增 `schemas/v1/{common,project-context,evidence,decision,artifact,task-state,task-input,task-result,approval-request,approval-event}.schema.json`、`docs/harness-contract.md`、`harness/contracts.py`、`harness/legacy.py`、`tests/test_contracts.py`、`tests/fixtures/harness/`；Harness 可选依赖单独锁定。 | 五类记录及执行输入输出各有正反例。测试非法版本、跨项目引用、替换链、迁移失败回滚和同一源重复导入。现有 Skill 无需安装新依赖。 |
| 3 编排 | 新增 `harness/{registry,router,store,orchestrator,gates,approval,adapters}.py`、`scripts/harness.py`、`docs/harness-architecture.md`、`tests/test_harness.py`。新增独立 Harness CI 或在现有 workflow 中加独立 job，`README.md` 增加可选入口。 | 战略到草稿在宿主或交接模式实跑，中断重启可恢复，改价标记受影响产物，保留旧版。无批准时模拟外部调用次数为零；同一批准只消费一次。现有安装、预览、重复安装保护成对回归。 |
| 4 评测 | 新增 `tests/test_harness_e2e.py`、`evals/gtm/{cases,protocol,results}`、`docs/harness-evaluation.md`。扩展 CI 跑离线回放与合成测试。 | 六类故障与权限用例有实际结果，配对 baseline 与 Harness 产物可复查。记录差值、失败和实验限制。无联网、凭证或真实外发的 CI 可复跑。 |

跨仓改动触发条件：仅当适配器无法无损承接现有交接格式时，再为确有需要的 Skill 增加可选输入输出说明。合并前分别复测独立入口，固定版本升级须经安装验收更新。项目数据库、产物与未脱敏回执保存在用户指定的仓库外目录。API Key 只由宿主凭证机制提供，不进入数据库、上下文、产物或日志。公开评测只用合成或获准脱敏样本。

## 5. 评测口径与发布门槛

| 场景 | 验收断言 |
|---|---|
| 正常流程 | 战略到内容草稿可追溯；可单独调用一个 Skill；完整流程再覆盖获客、销售和实验的角色交接。 |
| 上下文变化 | 新签涨价不改旧客价格；导出暂停使依赖该能力的产物待复核；同次变更保持无关记录，并撤销旧摘要对应的审批资格。 |
| 证据缺失 | 无证据的市场数据、效果、引语不进入可发布产物；给出草稿或带补证任务的阻塞。 |
| 工具失败 | 读失败记录原因与降级，超时造成结果未知不自动重试写操作，输出区分 pending、failed 和 confirmed。 |
| 恢复 | 中断前后 run_id、产物哈希、输入版本可核对；崩溃窗口与双次提交不会重复登记或发送。 |
| 权限 | 缺批准、过期、拒绝、已撤销、篡改载荷、跨项目及重复提交全部拒绝；注入文字不能成为批准。 |

两组用相同固定 SHA、输入、模型设置、工具权限、时限与预算，每题开独立上下文。原始五 Skill 组按现有普通文字交接，Harness 组使用契约和 checkpoint。预先定义必需产物与阻塞判据，再盲评事实、可用性和交接质量，保留失败样本。成功率记通过数/总数及配对差值，质量按事实准确、交付完整、变化传播和下一步可执行性评分。记录模型版本、调用数、token、实际费用或明确单价口径的估算、端到端及模型耗时、人工审批等待，缺数写 unknown。统计中位数与分布，样本不足不宣布领先。

下一阶段以契约、迁移和两段离线样例为首个合并单元，随后才引入持久编排。完整 MVP 的发布最低门槛为固定版本可安装、强制安全测试全过、离线端到端全过，并公开配对的效果及成本结果。现阶段只完成工程基线验证，没有 Harness 的成功率、质量、费用、耗时或相对提升数据。
