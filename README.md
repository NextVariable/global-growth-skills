# 海外增长 Skills · Global Growth Skills

五个独立 Skill，贯穿产品出海的市场选择、内容、获客、客户增长与实验复盘。按当前问题使用一个，也可以让它们接续工作。

| 你现在要解决什么 | Skill | 独立仓库 |
|---|---|---|
| 先进入哪个市场，服务谁，为什么客户会买 | 海外市场研究与 GTM 战略 | [global-gtm-strategy-skill](https://github.com/NextVariable/global-gtm-strategy-skill) |
| 怎样把产品价值讲清楚，制作官网、文章、社媒与视频内容 | 产品定位与增长内容 | [global-growth-content-skill](https://github.com/NextVariable/global-growth-content-skill) |
| 怎样发布产品，把合适的用户带来 | 产品发布与渠道获客 | [global-launch-acquisition-skill](https://github.com/NextVariable/global-launch-acquisition-skill) |
| 怎样推动购买、首次价值、续费和扩展 | 销售转化与客户增长 | [global-sales-retention-skill](https://github.com/NextVariable/global-sales-retention-skill) |
| 下一项增长动作值不值得做，结果说明什么 | 增长实验执行与复盘 | [global-growth-experiments-skill](https://github.com/NextVariable/global-growth-experiments-skill) |

各 Skill 的源文件、版本与测试维护在自己的仓库。本合集提供入口、选用方法、交接示例及指定版本的安装工具，不复制五套源文件，也不新增一个包办一切的第六 Skill。

## 安装

可去单个仓库按说明安装，也可用本合集的安装工具选择多个。需要 Git 和 Python 3.10+；安装过程只下载指定版本并复制技能目录，不执行下载内容中的脚本，不需要额外服务。

以 Codex 为例，先预览：

```bash
git clone https://github.com/NextVariable/global-growth-skills.git
cd global-growth-skills
python3 scripts/install.py --dest ~/.agents/skills
```

确认目录后执行：

```bash
python3 scripts/install.py --dest ~/.agents/skills --install
```

只安装后三个：

```bash
python3 scripts/install.py --dest ~/.agents/skills --only global-launch-acquisition global-sales-retention global-growth-experiments --install
```

已有同名目录时停止，不覆盖或混合旧版本。更新前自行保存旧版及个人修改，再选择一个空目标目录安装新版本进行比较。下载来源和固定版本见 [catalog.json](catalog.json)；它们是可复现的公开仓库快照，不表示自动跟随最新版本。重新加载客户端后调用对应 Skill。

## 从当前问题开始

还不知道市场与客户，用 `$global-gtm-strategy-skill`；已有方向、缺产品表达，用 `$global-growth-content`；有素材要发布获客，用 `$global-launch-acquisition`；有试用或意向客户要推进，用 `$global-sales-retention`；需要判断下一步怎么试、试完要不要继续，用 `$global-growth-experiments`。

不必每次顺序跑完五个。一次完整项目可以让第一个给出目标客户与价值假设，第二个生成适合这些客户的表达和资产，第三个组织渠道动作，第四个接住用户并帮助其购买和持续使用，第五个设计验证、检查结果，再把新证据交回相关部分。

```text
我们有一款面向英语团队的对账工具，已有目标客户和两次付费试点。
这次使用 $global-launch-acquisition，依据附上的定位和现成内容，
安排一条能带来合适试用团队的发布路径。每周只能支持四个新团队。
请准备具体执行包；素材不够时列明要交给内容 Skill 的任务，
收到主动需求后给客户增长 Skill 一份可接手的说明。
本次只准备，不对外发送或发布。
```

共享的是产品背景和证据，不是强制共用一个数据库。交接带上项目、目标客户、当前事实和未知、可用素材版本、实际动作状态、限制与下一任务即可。可直接使用 [普通文字交接示例](handoff-example.md)。各 Skill 都可独立接收用户资料，不要求安装其他四个。

## 验证与边界

各仓库分别记录结构检查、计算测试和模型任务试用。本合集检查清单、安装时的目录边界、冲突保护和下载失败处理，见 [验证说明](validation/README.md)。

```bash
python3 scripts/validate.py
```

Skill 能准备和分析，也能在现有工具与明确授权内执行；实际发布、触达、支出和客户系统修改需对应权限。模拟任务与工具检查不能证明真实获客、成交或留存收益。

Five independent Agent Skills for international GTM: strategy, positioning and content, launch and acquisition, sales and retention, and growth experiments. This repository is a versioned catalog and installer; each skill remains independently maintained.

[MIT License](LICENSE)。每个安装单元随带自身的许可及必要声明，安装工具完整保留。
