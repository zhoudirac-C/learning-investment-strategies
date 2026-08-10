# KPL 数据接入（情绪+资讯）— 设计文档

日期：2026-08-10
状态：已与用户对齐，待写实施计划
前置文档：`docs/design/kpl-api-inventory.md`（接口清单与抓包拓扑，下称「清单」）

## 定位与边界

把开盘啦（KPL）私有 API 中**已验证可重放**的两类接口接入本系统，工作日收盘后
自动落盘，补 M1「涨停池/情绪无缓存」缺口并积累产业新闻语料（产业链推导原料）。

本期范围：`Index.GetInfo` 情绪快照 + 资讯流（列表+全文）。

不做：

- 个股/龙虎榜/游资榜/席位接口（当前系统无消费方，超前建设）；
- token 自动刷新（私有 API 无刷新接口，失效只能重新抓包）；
- 直连通道数据（板块详情/题材库/异动提醒，证书固定，用户级抓包不可得——见清单）；
- 不修改 `src/qing_investment/`。

## 现状事实（设计依据，已核实）

- API 形态（清单「通用协议」节）：单入口
  `POST https://<子域>.longhuvip.com/w1/api/index.php?apiv=w47&PhoneOSNew=1&VerSion=6.2.20.5`，
  form 编码 body 必带 `UserID`/`Token`（32hex）/`DeviceID`（UUID），业务寻址
  `c=<控制器>&a=<动作>`，响应明文 JSON（中文 `\uXXXX` 转义，json 库原生可解）。
- token 寿命：2026-08-09 抓取的 token 在 08-10 全天有效（≥24h，上限未知）。
- 项目惯例：能力放 `src/investment_engine/<域>/` 包 + `scripts/` thin 入口
  （入口 `sys.path.insert` 指向 `src/`）；env 读取双写大小写
  （`DEEPSEEK_API_KEY or deepseek_api_key`，`blindtest/replay.py:40`）；
  cron 显式 `set -a && source .env && set +a`（shadow_daily 先例）；
  轻量 fetcher 用 stdlib `urllib.request`（`scripts/fetch_index_klines.py:13`）；
  `requests` 在 .venv 中仅是传递依赖、未在 pyproject 声明 → **用 stdlib，不加依赖**。
- `.gitignore` 已覆盖 `infra/data/` 与 `.env`；`tests/` 无 fixtures 目录，
  测试样本内嵌测试文件；tests 子目录不放 `__init__.py`。
- 本机 crontab 现状：15:35 pre_fetch_klines、15:40 shadow_daily（source .env）；
  调度登记与注销义务文档为 `docs/tasks/kline-daily-fetch-ops.md`。

## 关键决策（已与用户对齐）

| 决策点 | 结论 |
|---|---|
| 首批范围 | 情绪 + 资讯流；个股/席位/游资榜不接 |
| 调度节奏 | 收盘后一次，工作日 15:45（token 寿命未知，低频降低风控暴露） |
| 存储形态 | JSON 文件，不入 SQLite（可 diff、可直接审阅；需 SQL 时再从 JSON 回填） |
| HTTP 库 | stdlib `urllib.request`，不新增依赖 |
| 节假日 | 不特殊处理：拉到最近交易日数据，按 `--date` 落盘 |

## 架构

```
src/investment_engine/kpl/
├── __init__.py
├── client.py    # HTTP 层：KplClient + KplError/KplAuthError
├── emotion.py   # Index.GetInfo 情绪快照：拉取→解析→落盘
└── news.py      # 资讯：列表→全文→落盘
scripts/kpl_daily_fetch.py        # thin 入口
tests/investment_engine/test_kpl_client.py          # mock transport，不碰真实网络
tests/investment_engine/test_kpl_emotion.py         # 内嵌抓包实样裁剪样本
tests/investment_engine/test_kpl_news.py
infra/data/kpl/                   # 落盘根目录（随 infra/data/ 已 gitignore）
```

## 组件契约

### client.py

- `KplClient(user_id, token, device_id, timeout=10, retries=2)`
- `KplClient.from_env()`：读 `KPL_USER_ID`/`kpl_user_id`、`KPL_TOKEN`/`kpl_token`、
  `KPL_DEVICE_ID`/`kpl_device_id`（双写大小写惯例）；缺任一项抛 `KplError` 指明缺哪个。
- `post(subdomain, c, a, params) -> dict`：拼通用 URL，body 注入
  `UserID/Token/DeviceID` 与业务参数，form 编码 POST，返回解析后 JSON。
- 请求头：UA 提取自抓包实样；**H5 头（Origin/Referer/X-Requested-With）必须携带**——
  2026-08-10 实盘验证：不带时 `Index.GetInfo` 收盘后降级为空首页信息流
  `{List, list}`，带上即返回情绪数据块。
- 错误分级：网络超时/5xx → 退避重试（默认 2 次）；响应含业务错误 → `KplError`。
  **鉴权失败的响应特征未实测过**（抓包期间 token 一直有效）：实现按响应 JSON 的
  通用错误字段（如错误码非 0、msg 含登录/过期关键词）尽力判定为 `KplAuthError`，
  无法归类时统一 `KplError`；两种情况入口都以非 0 退出并在日志给出重抓指引，
  用户每日看日志即可感知。

### emotion.py

- `fetch_snapshot(client) -> dict`：子域 `apphwhq`，`c=Index&a=GetInfo`，
  全量 `View=2,3,4,5,7,8,9,10,11` 一次拉取。
- `save_snapshot(data, out_root, day) -> Path`：写
  `infra/data/kpl/emotion/<date>.json`。
- 输出 schema：

```json
{
  "date": "2026-08-10",
  "fetched_at": "2026-08-10T15:45:02",
  "daban":    { "tZhangTing": 0, "tFengBan": 0, "tDieTing": 0, "SZJS": 0,
                "XDJS": 0, "PPJS": 0, "ZHQD": 0, "ZRZTJ": 0, "ZRLBJ": 0, "...": "..." },
  "lianban":  [ ["代码","名称","涨幅","?","N连板","板块","板块;天数"], "..." ],
  "erban":    [ "..." ],
  "fengkou":  [ ["代码","名称","涨幅"], "..." ],
  "bankuai":  [ ["名称","涨幅","板块代码"], "..." ],
  "fengxiang": [ ["代码","名称","涨跌幅","板块标签"], "..." ]
}
```

- `daban` 块把 `DaBanList` 的关键字段平铺（字段含义见清单第 1 节）；
  list 型块保留原始数组，不做过度归一化（紧凑且信息无损）；
  `ensure_ascii=False`，便于人工审阅。

### news.py

- `fetch_list(client, day) -> list[dict]`：子域 `apparticle`，
  `c=IndexPlate&a=GetIndexList`（`view=1,2,3,4,6 & st=2 & Type=0`），
  按 `CreateTime`（unix）过滤出 `day` 当日条目。
- `fetch_full(client, msg_id) -> dict`：`c=ForumsMsgJX&a=GetInfo`（`MsgID & Tag=1`）。
- `save_news(items, out_root, day) -> Path`：写
  `infra/data/kpl/news/<date>/index.json`（当日全部条目 meta）+ 每篇
  `<MsgID>.md`（frontmatter：`id/title/create_time/type/msg_type/stocks/img_list`；
  正文为 HTML 转的纯文本，用 stdlib `html.parser`，不引第三方解析库）。

## 数据流

```
crontab 15:45（set -a && source .env && set +a）
  → scripts/kpl_daily_fetch.py
  → KplClient.from_env()
  → emotion.fetch_snapshot + save_snapshot
  → news.fetch_list(过滤当日) → 逐篇 fetch_full → save_news
  → stdout 摘要（情绪字段计数 / 资讯篇数 / 落盘路径）
```

幂等：当日目标文件已存在则跳过该部分，`--force` 强制覆盖重拉。

## 入口与调度

`scripts/kpl_daily_fetch.py` 参数：`--date`（默认今天）、`--out-root`
（默认 `infra/data/kpl`）、`--skip-emotion` / `--skip-news`、`--force`。
退出码：成功 0；`KplAuthError` 非 0 且日志输出「token 疑似失效，按
docs/design/kpl-api-inventory.md 的 Reqable 流程重抓」。

crontab 新增（接在现有两条之后）：

```
45 15 * * 1-5 cd <repo> && set -a && source .env && set +a && .venv/bin/python scripts/kpl_daily_fetch.py >> log/kpl_daily_fetch.log 2>&1
```

同步更新 `docs/tasks/kline-daily-fetch-ops.md` 的「现状」与「注销义务」两节
（把 kpl_daily_fetch 加进注销 grep 模式）。

## token 管理

- `.env` 增加三个小写 key：`kpl_user_id` / `kpl_token` / `kpl_device_id`
  （`.env` 已 gitignore，token 永不入库）。
- 失效路径：脚本非 0 退出 + 明确日志；重抓流程照清单「Reqable VPN 抓包操作摘要」节。
- token 有效期上限未知：接入后通过每日任务自然观察，失效时日志即信号。

## 测试

- `test_kpl_client.py`：mock transport（patch urlopen），验证 URL/body 构造、
  鉴权字段注入、重试与错误映射、from_env 缺项报错。
- `test_kpl_emotion.py`：内嵌裁剪后的 `Index.GetInfo` 实样，验证六块解析与
  落盘 JSON 结构。
- `test_kpl_news.py`：内嵌列表/全文实样，验证当日过滤、HTML 转纯文本、
  frontmatter 字段。
- 运行：`.venv/bin/pytest tests/investment_engine/test_kpl_client.py tests/investment_engine/test_kpl_emotion.py tests/investment_engine/test_kpl_news.py`

## 风险与合规（已向用户复述并确认）

- 私有 API 违反 App 用户协议，理论存在封号风险；每日每类一次调用的频率接近
  正常用户行为，风险较低但不为零。仅限个人研究用途。
- token 与抓包文件含登录态，`temp/kpl_capture/` 与 `.env` 均已 gitignore，不出本机。
- 开着 Reqable/mitmproxy 时 App 部分页面不可用（清单已载），抓包仅限维护 token 时。

## 验收标准

1. 三个测试文件全绿（mock/内嵌样本，不依赖网络与 token）。
2. 用有效 token 手动跑通一次真实拉取：情绪 JSON 六块齐全、资讯 md 可人工阅读。
3. cron 挂上后首个工作日 15:45 自动产出，`log/kpl_daily_fetch.log` 有摘要。
