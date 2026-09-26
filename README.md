# wqb-agent-tools

**WorldQuant BRAIN 研究工具包：可供 AI agent 调用，也可在 Python 和命令行中直接使用。**
**A WorldQuant BRAIN research toolkit for AI agents, Python scripts and the command line.**

### 给 agent 一套工具，让它自己去研究 / Give an agent the tools. Let it do the research.

这里没有预设的复杂工作流，只有一组干净、可靠的基础函数，覆盖 BRAIN 平台的各项操作。把它交给任意一个通用 agent，它就能自己查数据、写表达式、跑模拟、看结果，不断迭代。

No pre-built workflows — just a clean, reliable set of basic functions covering what the BRAIN platform offers. Hand it to any general-purpose agent and it can look up data, write expressions, run simulations, read the results and iterate on its own.

| 只做基础 / Basics only | 任意 agent 可用 / Works with any agent | 拿来即用 / Drop-in |
|---|---|---|
| 每个函数只做一件事，研究思路和流程交给 agent 自己决定。<br>Each function does one thing; the research strategy is left to the agent. | Python 调用或命令行调用都可以，返回 JSON，模型易读易用。<br>Call it from Python or the command line; JSON output that models read easily. | 只依赖标准库，复制到任何环境，填好账号即可运行。<br>Standard library only; copy it anywhere, add credentials, run. |

---

## 目录 / Contents
1. [简介 / Overview](#1-简介--overview)
2. [特点 / Features](#2-特点--features)
3. [目录结构 / Project layout](#3-目录结构--project-layout)
4. [安装 / Installation](#4-安装--installation)
5. [配置账号 / Credentials](#5-配置账号--credentials)
6. [使用方式 / Usage](#6-使用方式--usage)
7. [函数参考 / API reference](#7-函数参考--api-reference)
8. [命令行参考 / CLI reference](#8-命令行参考--cli-reference)
9. [快速示例 / Quick example](#9-快速示例--quick-example)
10. [测试 / Tests](#10-测试--tests)
11. [注意事项 / Notes](#11-注意事项--notes)
12. [许可证 / License](#12-许可证--license)

---

## 1. 简介 / Overview

本项目把 WorldQuant BRAIN 平台上做 alpha 研究需要的操作封装成函数和命令，每个功能都可以用一行代码或一条命令完成：
- 获取数据集、字段、算子和模拟设置选项；
- 提交模拟（回测）并获取结果、PnL 和年度统计；
- 运行提交前检查，查询自相关、生产相关和 Power Pool 相关性；
- 提交 alpha，修改属性和标签；
- 查询账户、比赛、排行榜；
- 阅读官方文档、社区论坛和帮助中心文章；
- 研究辅助工具：表达式校验、Power Pool 预算计数、本地相关性计算、稳健性评估、提交顺序规划、描述起草。

This project wraps the operations needed for alpha research on WorldQuant BRAIN into functions and commands, so each task is one line of code or one command:
- fetch datasets, data fields, operators and simulation setting options;
- run simulations (backtests) and fetch results, PnL and yearly statistics;
- run the pre-submission check and query self / production / Power Pool correlation;
- submit alphas and edit their properties and tags;
- query account data, competitions and leaderboards;
- read the official documentation, the community forum and help-center articles;
- research helpers: expression validation, Power Pool budget counting, local correlation, robustness reports, submission ordering and description drafting.

> 这是个人开发的非官方工具，与 WorldQuant 没有关系。
> This is an unofficial, independent project and is not affiliated with WorldQuant.

---

## 2. 特点 / Features

- **零依赖 / Zero dependencies**：只用 Python 标准库（Python ≥ 3.9），不需要 `pip install`。 / Standard library only (Python ≥ 3.9); nothing to install.
- **可移植 / Portable**：不依赖文件夹以外的任何文件，复制到任何位置都能运行。 / Self-contained; runs from any location.
- **适合 agent / Agent-friendly**：所有函数返回可转成 JSON 的 `dict` / `list`；命令行默认输出 JSON。 / Every function returns JSON-serialisable data; the CLI prints JSON.
- **稳健的网络层 / Robust networking**：自动登录与重新登录、cookie 持久化、限流和服务器错误自动重试、需要等待的接口自动轮询。 / Automatic (re-)authentication, cookie persistence, retries on rate limits and server errors, automatic polling.
- **两种使用方式 / Two interfaces**：Python API 和命令行，功能一一对应。 / Python API and CLI with matching features.

---

## 3. 目录结构 / Project layout

```
wqb-agent-tools/
├── LICENSE                    MIT
├── README.md
├── wqb.py                     命令行入口 / CLI entry point
├── credentials.example.json   账号配置模板 / credentials template
├── requirements.txt           无第三方依赖 / no third-party dependencies
├── .gitignore
├── wqb_tools/
│   ├── _http.py       内置 HTTP 会话 / built-in HTTP session (urllib)
│   ├── client.py      认证、重试、轮询、分页 / auth, retries, polling, pagination
│   ├── meta.py        模拟选项、地区、算子、权限 / simulation options, regions, operators, permissions
│   ├── data.py        数据类别、数据集、字段 / data categories, datasets, fields
│   ├── simulate.py    模拟（单个、批量、Multi-Simulation）/ simulations (single, batch, multi)
│   ├── alphas.py      alpha 查询、检查、相关性、提交、标签 / alphas, checks, correlation, submit, tags
│   ├── account.py     账户、活动、比赛、排行榜 / account, activity, competitions, leaderboards
│   ├── docs.py        官方文档 / official documentation
│   ├── forum.py       论坛与帮助中心 / forum and help center
│   ├── expr.py        表达式分析与模板展开 / expression analysis, template expansion
│   ├── validate.py    表达式完整校验 / full expression validation
│   ├── pp.py          Power Pool 预算与分类 / Power Pool budget and classification
│   ├── corr.py        本地相关性与提交顺序 / local correlation, submission ordering
│   ├── runner.py      实验运行器与实验日志 / experiment runner and ledger
│   ├── scout.py       数据集与字段挑选 / dataset and field scouting
│   ├── builder.py     信号筛选、组合、参数扫描 / screening, combinations, sweeps
│   ├── quality.py     稳健性报告 / robustness reports
│   ├── readiness.py   提交就绪评估、描述起草 / submission readiness, descriptions
│   ├── utils.py       通用工具 / helpers
│   └── cli.py         命令行实现 / CLI implementation
└── tests/             自检脚本 / self-check scripts
```

---

## 4. 安装 / Installation

```bash
git clone <this-repo-url> wqb-agent-tools
cd wqb-agent-tools
python wqb.py -h
```

不需要安装依赖。如果你的 Python 缺少系统 CA 证书，可以额外安装 `certifi`，工具包会自动使用。
No dependencies are required. If your Python lacks system CA certificates, install `certifi` and it will be used automatically.

---

## 5. 配置账号 / Credentials

**需要填写账号密码的文件：项目根目录下的 `credentials.json`。**
**The file to fill in: `credentials.json` in the project root.**

仓库中只提供模板 `credentials.example.json`。请复制一份并填写：
The repository only ships the template `credentials.example.json`. Copy it and fill it in:

```bash
cp credentials.example.json credentials.json        # Windows: copy credentials.example.json credentials.json
```

```json
{
  "email": "you@example.com",
  "password": "your-password"
}
```

`credentials.json` 已被 `.gitignore` 忽略，不会被提交到 git。保留单独的模板，是为了防止有人把填好的真实密码误传到仓库。
`credentials.json` is listed in `.gitignore`, so it is never committed. The separate template exists so that real credentials cannot be pushed by accident.

其他配置方式（按顺序查找，使用第一个找到的）/ Other options (checked in this order, first match wins):
1. 调用时传入 / passed in code: `W.login("you@example.com", "your-password")`
2. 环境变量 / environment variables: `WQB_EMAIL`, `WQB_PASSWORD`
3. 环境变量 `WQB_CREDENTIALS_FILE` 指定的文件 / a file named by `WQB_CREDENTIALS_FILE`
4. 项目根目录的 `credentials.json` / `credentials.json` in the project root
5. `~/.brain_credentials`，格式 / format: `["email", "password"]`

检查是否登录成功 / Verify:
```bash
python wqb.py whoami
```

如果账号开启了生物识别登录，运行 `python wqb.py login --wait`，在浏览器中打开给出的链接完成验证后回车。
If biometric sign-in is enabled, run `python wqb.py login --wait`, open the printed link in a browser, finish the verification and press Enter.

**本地缓存 / Local cache**：运行时数据（登录会话、算子与字段缓存、模拟去重缓存、PnL 缓存、实验日志）保存在 `.cache/`，已被 git 忽略；可用环境变量 `WQB_CACHE_DIR` 修改位置。
Runtime data (session cookies, operator/field caches, simulation de-duplication cache, PnL cache, experiment ledger) lives in `.cache/`, which is git-ignored; set `WQB_CACHE_DIR` to change the location.

---

## 6. 使用方式 / Usage

**Python**
```python
import sys; sys.path.insert(0, "path/to/wqb-agent-tools")
import wqb_tools as W

W.whoami()
r = W.simulate("rank(-ts_delta(close, 5))", mode="QUICK", region="USA", universe="TOP3000")
print(r["alpha"]["is"])
```

**命令行 / CLI**
```bash
python wqb.py simulate "rank(-ts_delta(close, 5))" --quick --universe TOP1000
```
所有命令默认输出 JSON；`--csv` 输出 CSV，`--out file.json|file.csv` 保存到文件，`--compact` 输出单行。
All commands print JSON; `--csv` prints CSV, `--out file.json|file.csv` saves to a file, `--compact` prints a single line.

**通用约定 / Conventions**
- 所有函数都接受可选参数 `client=`；不传时使用共享客户端，首次调用时自动登录。 / Every function accepts an optional `client=`; otherwise a shared client is used and signs in on first use.
- 大多数数据函数可指定 `region / delay / universe`，默认 `USA / 1 / TOP3000`。 / Most data functions take `region / delay / universe` (default `USA / 1 / TOP3000`).
- 出错时抛出 `W.BrainError`（`.status` 为 HTTP 状态码，`.payload` 为返回详情）。 / Errors raise `W.BrainError` (`.status` = HTTP status, `.payload` = response details).
- 未封装的接口可用 `W.raw(method, path)` 或 `python wqb.py raw GET /path` 调用。 / Endpoints not wrapped here can be called with `W.raw(method, path)` or `python wqb.py raw GET /path`.

---

## 7. 函数参考 / API reference

签名中的 `...` 表示还有其他可选参数，完整参数见 `help(W.<函数名>)`。
`...` means further optional arguments; see `help(W.<name>)` for the full signature.

### 7.1 登录与客户端 / Authentication & client

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.login(email=None, password=None, force=False)` | 登录，返回用户 ID、token 剩余时间和权限 | Sign in; returns user id, token expiry and permissions |
| `W.whoami()` | 当前登录状态 | Current authentication state |
| `W.get_client(**kw)` / `W.set_client(c)` | 获取 / 替换共享客户端 | Get / replace the shared client |
| `W.BrainClient(email, password, cache_dir, timeout, verbose)` | 客户端类 | Client class |
| `c.authenticate()` `c.auth_status()` `c.logout()` `c.complete_persona(url)` | 登录、查询状态、退出、完成生物识别 | Sign in, status, sign out, finish biometric sign-in |
| `c.get/post/patch/delete/options(path, ...)` / `c.request(method, path, ...)` | 带重试的原始请求 | Raw requests with retries |
| `c.poll(path, timeout)` | 轮询直到结果就绪 | Poll until the result is ready |
| `c.paginate(path, params, limit)` | 自动翻页（`limit=None` 取全部） | Automatic pagination (`limit=None` = all) |
| `W.resolve_credentials()` | 按顺序查找账号密码 | Resolve credentials in the documented order |
| `W.raw(method, path, params=None, body=None, poll=False)` | 调用任意接口 | Call any endpoint |
| `W.BrainError` / `W.BrainAuthError` / `W.PersonaRequired` | 异常类型 | Exception types |

### 7.2 平台元数据 / Platform metadata (`meta.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.simulation_options()` | 解析后的模拟设置选项 | Parsed simulation setting options |
| `W.raw_simulation_options()` | 原始选项 schema | Raw option schema |
| `W.list_regions()` | 各地区的 universe、delay、中性化选项 | Universes, delays and neutralizations per region |
| `W.validate_settings(settings)` | 检查设置组合，返回问题列表 | Check a settings dict; returns a list of problems |
| `W.list_operators(category=, scope=, search=)` | 算子列表 | Operator list |
| `W.operator_names(scope="REGULAR")` | 算子名称 | Operator names |
| `W.operator_doc(name)` | 算子条目及其文档 | Operator entry with its documentation |
| `W.account_simulation_defaults()` | 账户默认模拟设置 | Account default simulation settings |
| `W.permissions()` | 账户权限 | Account permissions |

### 7.3 数据 / Data (`data.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.data_categories()` | 数据类别 | Data categories |
| `W.list_datasets(region, delay, universe, category=, search=, order=, limit=50)` | 数据集列表 | List datasets |
| `W.get_dataset(id, region, delay, universe)` | 数据集详情 | Dataset details |
| `W.search_datasets(query, ...)` | 语义搜索数据集 | Semantic dataset search |
| `W.list_datafields(region, delay, universe, dataset_id=, search=, field_type=, category=, order=, limit=100)` | 字段列表 | List data fields |
| `W.get_datafield(id, ...)` | 字段详情 | Field details |
| `W.dataset_fields_table(id, ...)` | 数据集全部字段的精简表 | Compact table of all fields in a dataset |
| `W.all_datafield_ids()` | 所有字段 ID | All field ids |
| `W.request_datafield_visualization(id, ...)` | 请求字段可视化 | Request a field visualization |

### 7.4 模拟 / Simulation (`simulate.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.simulate(expr, mode="QUICK"\|"FULL", alpha_type="REGULAR", wait=True, use_cache=True, validate=False, **settings)` | 模拟一个 alpha，返回状态、alpha ID 和指标 | Simulate one alpha; returns status, alpha id and metrics |
| `W.simulate_batch(items, mode=, concurrency=3, multi=None, multi_size=10, on_result=, out_jsonl=, **settings)` | 批量模拟（自动 Multi-Simulation、并发、去重，结果按输入顺序） | Batch simulation (auto multi-simulation, concurrency, de-duplication, ordered results) |
| `W.build_payload(expr, alpha_type=, mode=, combo=, selection=, **settings)` | 构造模拟请求体（REGULAR / REGION_AGNOSTIC / SUPER） | Build a simulation payload (REGULAR / REGION_AGNOSTIC / SUPER) |
| `W.normalize_settings(dict)` | 规范化设置写法 | Normalise setting names and values |
| `W.set_default_settings(**kw)` / `W.use_account_defaults()` / `W.DEFAULT_SETTINGS` | 默认设置 | Default settings |
| `W.validate_payload(payload)` | 校验请求体 | Validate a payload |
| `W.start_simulation(payload)` | 只提交不等待 | Submit without waiting |
| `W.get_simulation(sim_id)` / `W.wait_simulation(sim_id)` | 查询进度 / 等待完成 | Check progress / wait for completion |
| `W.cancel_simulation(sim_id)` | 取消模拟 | Cancel a simulation |
| `W.promote_to_full(alpha_id, **overrides)` | 用 FULL 模式重新模拟 | Re-simulate in FULL mode |
| `W.cache_lookup(payload)` | 查询本地去重缓存 | Look up the local de-duplication cache |

### 7.5 Alpha (`alphas.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.get_alpha(id)` / `W.summarize_alpha(alpha_json)` | alpha 原始数据 / 精简视图 | Raw alpha / compact summary |
| `W.list_alphas(filters=None, status=, stage=, region=, date_from=, sharpe_min=, order="-dateCreated", limit=50)` | 筛选自己的 alpha（`filters` 如 `["is.sharpe>=1.5"]`） | Filter your alphas (`filters` e.g. `["is.sharpe>=1.5"]`) |
| `W.alphas_count_summary()` | 各阶段 alpha 数量 | Alpha counts by stage |
| `W.list_recordsets(id)` / `W.get_recordset(id, name)` | 数据表列表 / 某张数据表 | Record-set list / one record set |
| `W.get_pnl(id)` / `W.get_daily_pnl(id)` / `W.get_yearly_stats(id)` | 累计 PnL / 每日 PnL / 年度统计 | Cumulative PnL / daily PnL / yearly stats |
| `W.check_submission(id)` | 提交前检查 | Pre-submission check |
| `W.get_correlations(id, kind="self"\|"prod"\|"power-pool")` | 平台相关性 | Platform correlation |
| `W.before_after_performance(id, competition=None, team=None)` | 加入前后的表现对比 | Before/after performance |
| `W.update_alpha(id, name=, color=, tags=, category=, description=, favorite=, hidden=, clear=[])` | 修改属性 | Edit properties |
| `W.submit_alpha(id)` | 提交（不可撤销） | Submit (irreversible) |
| `W.super_alpha_components(id)` | SuperAlpha 成分 / Region-Agnostic 子 alpha | SuperAlpha components / region-agnostic children |
| `W.list_tags()` `W.get_tag(id)` `W.create_tag(name, alphas)` `W.update_tag(id, add=, remove=, rename=)` `W.delete_tag(id)` | 标签和列表管理 | Tag and list management |
| `W.tag_correlations(id, kind="inner"\|"self")` | 列表内部相关性 | Correlation within a list |

### 7.6 账户与社区 / Account & community (`account.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.me()` / `W.user_profile(user_id)` | 自己的资料 / 他人公开资料 | Your profile / another user's public profile |
| `W.activity(name, date_from=None)` | 活动统计（simulations / submissions / base-payment / other-payment / referrals） | Activity statistics |
| `W.simulation_counts(days=7)` | 最近的模拟次数 | Recent simulation counts |
| `W.diversity(grouping=...)` | 已提交 alpha 的分布 | Distribution of submitted alphas |
| `W.pyramid_alphas()` / `W.pyramid_multipliers()` / `W.pyramid_overview()` | 金字塔 alpha 数 / 乘数 / 合并视图 | Pyramid counts / multipliers / combined view |
| `W.streak()` `W.achievements()` `W.agreements()` `W.teams()` | 连续天数、成就、协议、团队 | Streak, achievements, agreements, teams |
| `W.consultant_summary()` / `W.osmosis_summary()` | 顾问汇总 / osmosis 汇总 | Consultant summary / osmosis summary |
| `W.messages(msg_type=None, limit=20)` / `W.messages_summary()` | 公告和通知 / 未读数 | Announcements & notifications / unread counts |
| `W.competitions(mine=False)` / `W.competition(id)` / `W.competition_board(id, board="leader")` | 比赛列表 / 详情 / 排行榜 | Competitions / details / leaderboard |
| `W.consultant_board(board="genius")` / `W.competition_levels()` | 顾问排行榜 / 比赛等级 | Consultant boards / competition levels |
| `W.events(limit=50, upcoming_only=False)` | 活动与讲座 | Events and webinars |

### 7.7 官方文档 / Documentation (`docs.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.list_tutorials()` / `W.docs_index()` | 文档目录 / 页面列表 | Documentation index / page list |
| `W.get_doc_page(page_id)` | 文档页面（转为 markdown） | A documentation page as markdown |
| `W.search_docs(query)` | 搜索文档 | Search the documentation |
| `W.dump_docs(out_dir)` | 导出全部文档 | Export all pages |
| `W.get_operator_doc(name)` | 算子文档 | Operator documentation |
| `W.example_alphas(limit=50)` / `W.video_courses()` | 官方示例 / 视频课 | Official examples / video courses |

### 7.8 论坛与帮助中心 / Forum & help center (`forum.py`)

先获取客户端：`fo = W.get_forum()`。 / Get a client first: `fo = W.get_forum()`.

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `fo.topics()` | 所有版块 | All topics |
| `fo.posts(topic_id=None, sort_by="created_at", limit=30)` | 最新帖子 | Latest posts |
| `fo.post(post_id, comments=True)` / `fo.comments(post_id)` | 帖子全文与评论 / 评论 | Post with comments / comments |
| `fo.search_posts(query, topic_id=None, limit=25)` | 搜索帖子 | Search posts |
| `fo.crawl_topic(topic_id, out_dir=None, limit=50, since_id=None)` | 增量抓取版块并保存为 JSON | Incrementally crawl a topic to JSON |
| `fo.search_articles(query)` / `fo.articles(...)` / `fo.article(id)` | 帮助中心文章：搜索 / 列表 / 正文 | Help-center articles: search / list / body |
| `fo.categories()` / `fo.sections(category_id=None)` | 帮助中心分类 / 栏目 | Help-center categories / sections |
| `fo.get(path, params)` | 调用任意论坛 API | Call any forum API path |

### 7.9 表达式工具 / Expression tools (`expr.py`, `validate.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.validate_expression(expr, region, delay, universe, check_fields=True)` | 完整校验：语法、算子、参数、字段可用性与类型 | Full validation: syntax, operators, arguments, field availability and types |
| `W.validate_many(exprs, ...)` | 批量校验 | Validate many |
| `W.parse_expression(expr)` / `W.parse_signature(definition, name)` / `W.operator_signatures()` | 语法树 / 算子签名解析 | Syntax tree / operator signature parsing |
| `W.field_info(fields, region, delay, universe)` | 字段类型、所属数据集、可用性 | Field type, dataset and availability |
| `W.check_expression(expr, operators=None, fields=None)` | 快速检查 | Quick lint |
| `W.analyze_expression(expr)` | 结构分析 | Structural analysis |
| `W.expand_template(tpl, values)` / `W.template_placeholders(tpl)` | 模板展开 / 列出占位符 | Template expansion / placeholders |

### 7.10 Power Pool 与相关性 / Power Pool & correlation (`pp.py`, `corr.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.operator_count(expr)` | 统计算子数 | Count operators |
| `W.pp_budget(expr=None, alpha_id=None, ...)` | Power Pool 预算（算子数、字段数、数据集） | Power Pool budget (operators, fields, datasets) |
| `W.field_datasets(fields, ...)` | 字段所属数据集 | Dataset of each field |
| `W.classify_alpha(id)` / `W.classify_many(ids)` | 按提交检查结果给 alpha 分类 | Classify alphas from the submission check |
| `W.correlation_matrix(ids, years=4)` | 候选之间的本地相关性矩阵 | Local correlation matrix between candidates |
| `W.correlation(a, b)` | 两个 alpha 的相关性 | Correlation of two alphas |
| `W.self_correlation(id, kind="regular"\|"power_pool")` / `W.power_pool_correlation(id)` | 本地自相关 / Power Pool 相关性 | Local self / Power Pool correlation |
| `W.plan_submission_order(ids, kind=, threshold=None)` | 规划互不冲突的提交顺序 | Plan a non-conflicting submission order |
| `W.submitted_pool(kind=, region=)` / `W.is_pure_power_pool(alpha)` | 已提交 alpha 池 / 是否纯 Power Pool | Submitted pool / pure Power Pool check |
| `W.pnl_series(id)` / `W.daily_returns(pnl, years)` | PnL 序列 / 每日收益 | PnL series / daily returns |

### 7.11 研究工作流 / Research workflow (`runner.py`, `scout.py`, `builder.py`, `quality.py`, `readiness.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.run_experiment(exprs, tag, region=, universe=, mode="FULL", pp_budget_check=False, reuse=True, **settings)` | 实验运行器：校验、复用历史结果、批量模拟、写日志、返回指标行 | Experiment runner: validate, reuse past runs, simulate, log, return metric rows |
| `W.results_table(rows)` / `W.metrics_row(result)` | 对比表格 / 单个结果拉平 | Comparison table / flatten one result |
| `W.find_tried(field=, text=, tag=, min_sharpe=, region=)` / `W.Ledger(path)` / `W.default_ledger()` | 查询实验日志 | Query the experiment ledger |
| `W.simulation_quota()` | 当日模拟额度 | Daily simulation quota |
| `W.scout_datasets(region, delay, universe, purpose=, exclude=[])` | 数据集打分排序 | Rank datasets |
| `W.representative_fields(ds, ..., n=16, keyword=None)` / `W.field_families(ds, ...)` | 挑选代表字段 / 字段族 | Representative fields / field families |
| `W.is_market_wide(desc)` / `W.is_metadata(field_id)` | 字段过滤规则 | Field filters |
| `W.screen_fields(terms, tag, templates=None, **run_kwargs)` | 批量筛选信号（自动翻转方向） | Screen signals (automatic sign flip) |
| `W.build_combos(signals, sizes=(2,3), max_fields=3, max_ops=8)` | 构造信号组合 | Build signal combinations |
| `W.sweep(expr, tag, grid, **run_kwargs)` | 参数网格扫描 | Parameter grid sweep |
| `W.robustness_report(id)` / `W.compare_robustness(ids)` | 稳健性报告与质量分 | Robustness report and quality score |
| `W.submission_readiness(ids, purpose=, quota_left=None)` | 提交就绪评估与推荐顺序 | Submission readiness and recommended order |
| `W.draft_pp_description(id, idea)` / `W.check_description(text, expression, others=[])` | 起草 / 检查 Power Pool 描述 | Draft / check a Power Pool description |
| `W.active_rules(unsubmitted_alpha_id)` | 当前主题、额度与测试门槛 | Active themes, quotas and test limits |

### 7.12 工具函数 / Utilities (`utils.py`)

| 调用方式 / Usage | 作用 | Description |
|---|---|---|
| `W.recordset_to_dicts(payload)` | 数据表转字典列表 | Record set to list of dicts |
| `W.html_to_text(html)` | HTML 转纯文本 | HTML to plain text |
| `W.to_csv(rows, path=None)` | 字典列表转 CSV | Rows to CSV |

---

## 8. 命令行参考 / CLI reference

用法 / Usage：`python wqb.py <command> [options]`。每条命令的参数见 / see `python wqb.py <command> -h`。

| 类别 / Group | 命令 / Commands |
|---|---|
| 认证与元数据 / Auth & metadata | `login` `whoami` `logout` `permissions` `options` `regions` `defaults` `operators` `op-doc` |
| 数据 / Data | `categories` `datasets` `dataset` `dataset-search` `fields` `field` `field-ids` `visualize` |
| 模拟 / Simulation | `simulate` `payload` `batch` `sim-status` `sim-wait` `sim-cancel` `promote` |
| Alpha | `alpha` `alphas` `alpha-counts` `recordsets` `recordset` `pnl` `yearly` `check` `corr` `before-after` `update-alpha` `submit` `components` |
| 标签 / Tags | `tags` `tag` `tag-create` `tag-update` `tag-delete` `tag-corr` |
| 账户与社区 / Account & community | `me` `activity` `diversity` `pyramids` `streak` `achievements` `consultant` `osmosis` `messages` `teams` `competitions` `competition` `board` `genius` `events` |
| 文档 / Docs | `docs` `doc` `docs-dump` `examples` `videos` |
| 论坛与文章 / Forum & articles | `forum-topics` `forum-posts` `forum-post` `forum-search` `forum-crawl` `article-search` `article` `articles` `help-categories` `help-sections` |
| 表达式 / Expressions | `validate` `lint` `expand` |
| Power Pool 与相关性 / Power Pool & correlation | `pp-budget` `pp-classify` `corr-matrix` `self-corr-local` `submit-order` |
| 研究工作流 / Research workflow | `scout` `rep-fields` `experiment` `tried` `quota` `robustness` `readiness` `rules` `desc-draft` `desc-check` |
| 通用 / Generic | `raw` |

`batch` 和 `experiment` 的输入文件支持 `.txt`（每行一个表达式）、`.json`（列表）和 `.jsonl`（每行一个 JSON）。
Input files for `batch` and `experiment` can be `.txt` (one expression per line), `.json` (a list) or `.jsonl` (one JSON per line).

---

## 9. 快速示例 / Quick example

```python
import wqb_tools as W
S = dict(region="USA", universe="TOP3000", neutralization="SUBINDUSTRY", decay=4)

fields = W.representative_fields("pv1", "USA", 1, "TOP3000", n=8)        # 挑字段 / pick fields
sig    = W.screen_fields(fields, "screen", **S)                          # 筛选 / screen
rows   = W.run_experiment(W.build_combos(sig), "combos", **S)            # 组合 / combine
print(W.results_table(rows))                                             # 对比 / compare

cands  = [r["alpha_id"] for r in rows if (r["sharpe"] or 0) >= 1]
print(W.submission_readiness(cands, purpose="regular"))                  # 提交前评估 / readiness
```

命令行 / CLI:
```bash
python wqb.py validate "rank(ts_mean(close, 20))"
python wqb.py simulate "rank(ts_mean(close, 20))" --quick
python wqb.py alphas "is.sharpe>=1.5" --order "-is.sharpe" --limit 10 --csv
python wqb.py readiness <alpha_id_1> <alpha_id_2>
```

---

## 10. 测试 / Tests

`tests/` 中是自检脚本，用来确认工具包在你的账号上工作正常。
`tests/` contains self-check scripts that confirm the toolkit works with your account.

```bash
python tests/smoke_test.py               # 调用全部只读接口 / call all read-only endpoints
python tests/smoke_test.py --simulate    # 另测模拟功能（约 10 次模拟）/ also test simulations (~10)
python tests/smoke_test.py --mutate      # 另测可撤销的写操作 / also test reversible writes
python tests/validate_pp_corr.py         # 与平台数值对比 PP 预算、分类和相关性 / compare with platform numbers
python tests/validate_expressions.py     # 表达式校验器测试 / expression validator tests
python tests/validate_lab_tools.py       # 研究工作流工具测试 / research workflow tool tests
```

---

## 11. 注意事项 / Notes

- 不要提交 `credentials.json` 和 `.cache/`（已在 `.gitignore` 中）。 / Never commit `credentials.json` or `.cache/` (both are git-ignored).
- `submit_alpha` 等写操作会直接修改你的平台账号，其中提交不可撤销；命令行提交需要加 `--yes`。 / Write operations such as `submit_alpha` change your account; submission is irreversible and the CLI requires `--yes`.
- 请遵守 WorldQuant BRAIN 的服务条款并控制请求频率。 / Follow the WorldQuant BRAIN terms of service and keep request rates reasonable.
- 平台接口可能变化，可运行 `tests/smoke_test.py` 检查。 / The platform API may change; run `tests/smoke_test.py` to check.

---

## 12. 许可证 / License

本项目采用 [MIT License](LICENSE)。
This project is licensed under the [MIT License](LICENSE).
