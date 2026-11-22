# GTM Harness V1.0 Release Readiness

版本 **1.0.0-rc.1**。完整五阶段流程已通过离线 Fixture 和一次真实 Codex 运行。战略到获客另有一轮公开产品配对测试。所有产出为研究决策或供审查的草稿，正式版还需扩大真实业务样本、工具接入与权限验收。

## 基线和交付文件

本轮从合集 `757f98a` 开发。隔离克隆五个公开 main 后逐仓运行 `scripts/validate.py`，五套均退出 0。Hub 安装目录和独立使用方式继续兼容原版本。执行基线为 catalog 的固定 SHA。

| Skill | Catalog SHA | 本轮核对的 GitHub main |
|---|---|---|
| Strategy | `b9a3f9d46e68e6959211ac5ebccb4a5bd35ead12` | `beb359e0ccf1afb5535ff8d42bc904e682afbc7e` |
| Content | `d3d8aa367ace0e9ff27ce7a8a21e3ebd5e28140e` | `d05f6813e46973fc2a10cb64e7e096d55d040958` |
| Acquisition | `a5bfa7c3d5a64b61bcb17491ad96a9b34269b96e` | `b4070afa5d2e6351a1be9d1b5e4eebc3fa0d86cc` |
| Sales | `7c201004d3aba3896808660e56ba4a74b64322b6` | `5e62b33cc6581468c07eff352575dbae4d5b45fc` |
| Experiments | `fb1060e4ff5c80dcfb00b2c68099a511b1e5eed4` | `e873fc413d0b7a1b075271b15db0ff06cd0c7fb5` |

- 编排与兼容迁移见 `harness/planning.py`、`registry.py`、`orchestrator.py`、`store.py` 及 `schemas/v1/harness.schema.json`。
- 证据与权限见 `harness/research.py` 与 `harness/gateway.py`。
- 宿主和交接见 `harness/codex_host.py`、`adapters.py` 与 `__main__.py`。
- CLI 入口和说明见 [README](README.md)、[架构及迁移](docs/harness.md)、[Skill 契约](docs/harness-contract.md) 与 [变更日志](CHANGELOG.md)。示例位于 `examples/harness/`。
- 新增测试位于 `tests/harness/`，CI 沿用 `.github/workflows/harness.yml` 上传完整测试日志。实际运行输入和结果位于 [evals/v1](evals/v1/README.md)。

## 验收结果

| 场景 | 结果及限制 |
|---|---|
| A 完整 AI SaaS GTM | Fixture 和真实 Codex 均完成五阶段。真实运行使用合成业务输入，实验产物记录了定位、获客与销售草稿 ID。 |
| B 只做获客 | 通过，CLI 只执行获客。 |
| C 改价 | 通过，只重建价格草稿、销售与实验方案，定位、能力及获客保留原 ID。 |
| D 重启 | 通过，独立进程读取战略 checkpoint。另测旧尝试迟到、事务回滚与重试。 |
| E 缺证据 | 通过，市场结论为待复核，伪造结构化引用失败，缺必要产品字段时阶段阻塞。 |
| F 权限 | POSIX Mock 通过，覆盖无授权、到期、撤回、篡改载荷、跨项目、重复及结果未知。Windows 明确跳过依赖 POSIX 用户身份的三项用例。外部真实执行器不在本版。 |
| G 真实宿主 | 通过，真实 Codex 完成五阶段及独立的 Strategy → Launch 配对运行。实际加载固定 Git 中的 Skill 指令与 Markdown 参考，保存操作耗时、请求模型、宿主完成事件、token 和文档哈希。 |

A–D 的独立 CLI 执行见 [Fixture 回执](evals/v1/fixture-acceptance.json)。Mock CLI 的拒绝、批准与重复拒绝见 [Mock 回执](evals/v1/mock-acceptance.json)。本地 Harness 通过 31/31 项，安装器通过 10/10 项。开发中的一次失败为内容单独运行时缺战略决策导致 Fixture 抛错，已改为使用现有项目背景并增加回归。首轮 Windows CI 的 SQLite 迁移测试清理失败，原因是测试留下了一个打开的连接，已在 `14fe83c` 修复。修复提交在 Linux、macOS、Windows 三平台均通过。见 [首轮失败记录](https://github.com/NextVariable/global-growth-skills/actions/runs/44983898840)与[修复后的 CI](https://github.com/NextVariable/global-growth-skills/actions/runs/44984080309)。故障注入包括模型超时、SQLite 中途失败与 Mock 执行未知。通过的负向用例表示系统正确拒绝或恢复。

## 真实模型与配对数据

[公开产品输入](evals/v1/public-project.json)来自该项目的开源功能，英语独立创始人是待验证细分。两组使用相同固定 Skill 文档、Codex CLI、本次明确请求的 `gpt-6.2-sol`，每次调用均为独立只读无工具进程。A 用明确的人工交接字段选择做直接调用回放，B 在 Harness 里自动传递决策。两种路径向获客传递的格式不同，代表各自实际交接方式。样本只有一个任务与两个角色，未盲评也未测量人工交接用时。

| 路径 | 真实完成调用 | 输入 token | 输出 token | 端到端 |
|---|---:|---:|---:|---:|
| A 直接调用与人工交接回放 | 2/2 | 71,161 | 2,325 | 64.662 s |
| B 自动编排 | 2/2 | 71,238 | 2,216 | 62.033 s |

保留 [A 原始输出和回执](evals/v1/manual-public-product.json) 和 [B 状态和回执](evals/v1/harness-public-product.json)。B 另有一次合成业务输入上的[真实宿主试运行](evals/v1/host-synthetic-input.json)。它调用真实模型，和 Fixture 的固定输出分开。

[真实五阶段运行](evals/v1/host-full-workflow.json)以[合成会议工具输入](examples/harness/project.json)完成 5/5 阶段、7/7 次模型调用，共形成一份战略决策和六份草稿。宿主回执合计 245,082 输入 token（其中 24,192 为缓存输入）与 5,970 输出 token，七次宿主调用累计 180.953 秒。市场依据缺失，决策保留待审状态且无引用。产物将访谈、触达、试点付款与实验列为后续步骤，未记录这些行动已发生。

人工审查两组草稿均承接同一拟议受众、证据缺口和自愿试点，未宣称已获客、已发布或已有增长。B 持久记录决策 ID 和依赖，A 保留人工整理的交接文字。B 在单次样本中少用 109 输出 token、多用 77 输入 token，墙钟少 2.629 秒。这个差异包含模型输出变化和并行运行时的调度波动，不能解释为 Harness 的普遍提速。账单及实际费用未知，保留计量明细。执行 `scripts/compare_gtm.py --help` 可复跑两组。

## 安全审查与正式版缺口

已测试：宿主工具关闭、固定 Git 内容装载、输出拒绝动作字段、SQLite 项目隔离、当前上下文版本和载荷绑定、批准消费与未知结果停止。当前审批信任本机 POSIX 用户和数据库所有权，没有远程认证、多人 RBAC 或真实写工具。所有公开运行都使用合成或公开产品资料。

下一步需要用多个真实业务任务覆盖五个角色，采用独立评审和实际成本对账。证据模块需增加受控的实际搜索/浏览/MCP 只读提供器，以及对自然语言事实、引文与证据支持关系的人工标注评测。来源集合当前整体修订，后续可进一步细化到逐来源依赖。Claude Code 目前可以用手工交接，自动适配器未验收。新接入的外部写操作需独立进行身份、确认回执和幂等验收。
