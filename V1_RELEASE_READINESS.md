# GTM Harness V1.0 Release Readiness

版本 **1.0.0**。已验收 HEAD `251a52f0382c34b23392470ed1fd61b842cf4c0e`，PR [#1](https://github.com/NextVariable/global-growth-skills/pull/1)，Release Gate **PASS**。完整五阶段已通过离线 Fixture 与真实 Codex 运行；V1.0 不新增运行时功能，只修正发布文档并记录验收边界。机器可读记录见 [release-gate-v1.0.0.json](validation/release-gate-v1.0.0.json)，产品说明见 [docs/v1.0.0-release.md](docs/v1.0.0-release.md)。

## 基线和交付文件

分支 `feat/rc3-research-quality` 基于已验收 RC3；执行基线为 catalog 的固定 SHA。本轮未改变任何 Skill 版本或运行时行为。

| Skill | Catalog SHA |
|---|---|
| Strategy | `b9a3f9d46e68e6959211ac5ebccb4a5bd35ead12` |
| Content | `d3d8aa367ace0e9ff27ce7a8a21e3ebd5e28140e` |
| Acquisition | `a5bfa7c3d5a64b61bcb17491ad96a9b34269b96e` |
| Sales | `7c201004d3aba3896808660e56ba4a74b64322b6` |
| Experiments | `fb1060e4ff5c80dcfb00b2c68099a511b1e5eed4` |

- 编排与兼容迁移见 `harness/planning.py`、`registry.py`、`orchestrator.py`、`store.py` 及 `schemas/v1/harness.schema.json`。
- 证据与来源分类见 `harness/research.py`、`harness/evidence.py`、`harness/provenance.py`；权限见 `harness/gateway.py`。
- 宿主和交接见 `harness/codex_host.py`、`adapters.py` 与 `__main__.py`。
- CLI 入口和说明见 [README](README.md)、[架构及迁移](docs/harness.md)、[Skill 契约](docs/harness-contract.md)、[变更日志](CHANGELOG.md) 与 [V1.0 发布说明](RELEASE_NOTES.md)。
- 示例位于 `examples/harness/`；RC2 与 RC3 的真实运行记录位于 `evals/rc2/`、`evals/rc3/`。

## V1.0 验收结果

| 检查 | 结果 |
|---|---|
| Harness 单元与集成测试 | 125/125 通过 |
| 安装器测试 | 10/10 通过 |
| 产品场景（fixture，无模型调用） | 10/10 通过 |
| RC3 确定性评测（fixture + reference） | 8 次运行，0 错误，0 阶段失败 |
| Catalog、Schema 与文档链接 | 5 个独立仓库，通过 |
| 隐私扫描（已跟踪文件） | 无当前发现 |
| 静态分析（ruff E4/E7/E9/F） | 通过 |
| 干净目录安装与离线导出 | 安装 5 个固定版本；init/start/step/resume/export 全部退出 0 |
| `251a52f` GitHub Actions | 18/18 项检查成功 |

Fixture 与 Reference 只验证流程结构与评分卡区分度，不代表模型质量或真实客户效果。

## 真实模型验收

执行于 `faa29ad`，使用已登录 ChatGPT Codex，请求 `gpt-6.2-sol`，移除了独立 API Key；宿主未提供可核对账单，费用记为 `not_measured`。

| 工作流 | 宿主完成调用 | 输入 / 输出 token | 缓存输入 token | 模型命令墙钟 | Harness 阶段失败 |
|---|---:|---:|---:|---:|---:|
| Strategy → Acquisition → Experiments | 3/3 | 111,390 / 5,689 | 0 | 149.42 秒 | 0 |
| 完整五阶段，含一次重试 | 10/10 | 370,350 / 11,668 | 0 | 376.82 秒 | 1 |

- Strategy 原始输出中，门槛、观察期和独立条件均为 `proposed`。操作者通过 `revise-decision` 批准后，定位、获客、销售和实验的结构化引用绑定到同一 `decision_id`、第 2 版契约和批准回执 SHA256。
- 两套运行均沿用“至少 2 名独立完成者、来自不同项目、观察 14 天、预算 0 USD”，未用 3 人或 60% 替换既定门槛。
- 完整运行的内容阶段首次因 `citation is missing, stale or contradicted` 被拒绝，未留下部分草稿；从同一 revision 2 检查点重试后五阶段完成。
- 最后一处来源分类修复 `251a52f` 由 `tests/harness/test_provenance.py` 的 19 个确定性用例覆盖，未重复执行五阶段模型评测。

证据分层：工程验证 **PASS**；真实模型执行 **已在 `faa29ad` 记录**；真实商业效果 **`not_measured`**。没有执行真实发布、触达、CRM 写入或广告消费，也不宣称自动获客、自动成交或收入提升。

## 历史验收（RC1 记录，能力范围沿用）

`1.0.0-rc.1` 从合集 `757f98a` 开发，隔离克隆五个公开 main 后逐仓运行 `scripts/validate.py`，五套均退出 0。以下场景证明 V1.0 沿用的编排与权限能力；数字属于 RC1 运行，不替代 V1.0 本轮的确定性结果。

| 场景 | 结果及限制 |
|---|---|
| A 完整 AI SaaS GTM | Fixture 和真实 Codex 均完成五阶段。真实运行使用合成业务输入，实验产物记录了定位、获客与销售草稿 ID。 |
| B 只做获客 | 通过，CLI 只执行获客。 |
| C 改价 | 通过，只重建价格草稿、销售与实验方案，定位、能力及获客保留原 ID。 |
| D 重启 | 通过，独立进程读取战略 checkpoint。另测旧尝试迟到、事务回滚与重试。 |
| E 缺证据 | 通过，市场结论为待复核，伪造结构化引用失败，缺必要产品字段时阶段阻塞。 |
| F 权限 | POSIX Mock 通过，覆盖无授权、到期、撤回、篡改载荷、跨项目、重复及结果未知。Windows 明确跳过依赖 POSIX 用户身份的三项用例。外部真实执行器不在本版。 |
| G 真实宿主 | 通过，真实 Codex 完成五阶段及独立的 Strategy → Launch 配对运行。实际加载固定 Git 中的 Skill 指令与 Markdown 参考，保存操作耗时、请求模型、宿主完成事件、token 和文档哈希。 |

RC1 本地 Harness 记录为 31/31，安装器 10/10。开发中的一次 Fixture 失败与 Windows SQLite 迁移清理失败均已在当时修复并加入回归；修复后 Linux、macOS、Windows 三平台通过（[首轮失败记录](https://github.com/NextVariable/global-growth-skills/actions/runs/44983898840)、[修复后的 CI](https://github.com/NextVariable/global-growth-skills/actions/runs/44984080309)）。A–D 的独立 CLI 执行见 [Fixture 回执](evals/v1/fixture-acceptance.json)，Mock 拒绝、批准与重复拒绝见 [Mock 回执](evals/v1/mock-acceptance.json)。

RC1 的另一组真实模型配对数据（直接调用与自动编排各 2/2 次调用）保留在 [A 原始输出](evals/v1/manual-public-product.json) 与 [B 状态和回执](evals/v1/harness-public-product.json)；样本只有一个任务与两个角色，不能推断普遍提速或质量提升。

## 安全审查与正式版缺口

已测试：宿主工具关闭、固定 Git 内容装载、输出拒绝动作字段、SQLite 项目隔离、当前上下文版本和载荷绑定、批准消费与未知结果停止。审批信任本机 POSIX 用户和数据库所有权，没有远程认证、多人 RBAC 或真实写工具。所有公开运行均使用合成或公开产品资料。

正式版仍需扩大真实业务样本、接入独立语义评审与真实行为证据、对完整工作流做盲评与人工时间测量，并准备真实模型费用对账和生产环境身份治理。来源分类依赖结构化数值匹配，非常规写法需人工复核。Claude Code 目前可以用手工交接，自动适配器未验收。新接入的外部写操作需独立进行身份、确认回执和幂等验收。

## 发布动作

- PR [#1](https://github.com/NextVariable/global-growth-skills/pull/1) 已以 merge commit `7112a7df48d59419594619d51d279e6d0f20fb00` 合并到 `main`；`Harness fixture tests` 与 `Validate` 在该提交上均通过。
- 运行时版本号已从 `1.0.0-rc.3` 对齐为 `1.0.0`，未改变运行时行为。
- 尚未创建 GitHub Release 或 git tag；该动作需 Product Owner 单独授权。
