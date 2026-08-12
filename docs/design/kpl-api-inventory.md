# 开盘啦（KPL）私有 API 接口清单（抓包自 Android App 6.2.20.5）

> 来源：mitmproxy 抓取本人账号流量整理，仅限个人研究用途，遵守 App 用户协议风险自负。
> 抓包原始文件在 `temp/kpl_capture/`（已 gitignore，含 token，勿外泄）。
> 场次：2026-08-09（周日，家庭 Wi-Fi 拓扑）、2026-08-10 上午盘中（USB+热点拓扑，见文末）、
> 2026-08-10 下午盘中（Reqable VPN 模式，见「第二条通道」节）。

## 通用协议

- **入口**：`POST https://<子域>.longhuvip.com/w1/api/index.php?apiv=w47&PhoneOSNew=1&VerSion=6.2.20.5`
- **编码**：`application/x-www-form-urlencoded`，业务参数在 body
- **鉴权**：每个请求 body 必带 `UserID` / `Token`（32 位 hex，登录态）/ `DeviceID`（UUID）
  - token 存 `.env` 的 `kpl_token`（待接入时添加）；失效需重新抓包登录流程
  - 有效期观察：2026-08-09 抓取的 token 在 08-10 全天正常使用，**至少 24h+**，上限待观察
- **业务寻址**：`c=<控制器>&a=<动作>`，响应均为明文 JSON（中文为 `\uXXXX` 转义）
- **子域即服务划分**：applhb=主服务，apphwhq=行情/情绪，apparticle=资讯，apphis=历史，
  apppage=内嵌 H5，appicon=头像，applog=埋点，apphotfix=热更新

## 接入实测补充（2026-08-10 收盘后实盘验证）

- **H5 请求头必须携带**：`Origin/Referer: https://apppage.longhuvip.com(/)+
  X-Requested-With: com.aiyu.kaipanla`。不带时 `Index.GetInfo` 在收盘后降级返回
  空首页信息流 `{List, list, errcode}`（盘中是否正常未对照）；带上即正常返回情绪数据块。
  `Day` 等额外参数无此效果。已实现于 `investment_engine/kpl/client.py` 的 `H5_HEADERS`。
- **付费专栏条目全文不可得**：资讯列表 `MsgTop.List` 混有两类条目——普通资讯
  （5 位 ID，ForumsMsgJX.GetInfo 可读）与付费专栏/券商研报转载（6 位 ID 978xxx，
  带 `AID/Account/SpecType` 字段），后者全文返回 `errcode=1130`（msg 为空，
  本账号无权限）。`kpl/news.py` 逐篇容错跳过并记入 index.json（`fetched=false`）。
- 列表响应除 `MsgTop` 外还有 `TCop`（题材关键词流，CID/Kword/Stocks/Title）与
  `AiTop`（AI 推送，含 PushUrl），本期未接入，留作后续候选。
- 收盘后 16:50 实测：情绪六块（DaBanList/PHBList/ErBanList/FKYDSixList/BaceFaceList/
  CWeatherVaneList）齐全，ErBanList 收盘后为空数组属正常。
- token 第二日（2026-08-10 16:50）仍有效，累计 ≥30h。

## 已验证接口（按系统价值排序）

### 1. 市场情绪/打板大盘/连板梯队/盘口异动 —— 补 M1「涨停池/情绪无缓存」缺口

```
c=Index&a=GetInfo    子域: apphwhq    参数: View=<逗号分隔的数据块 ID>
```

- **View 是数据块选择器**。观察到的组合：`4,5,11` / `1,7,8,9,10,11` / `2,7,9,10` / `3` /
  全量 `2,3,4,5,7,8,9,10,11`；页面↔View 映射未逐一对应，接入时直接拉全量。
  2026-08-10 盘中 25 次实时刷新验证结构稳定。
- 响应关键字段（2026-08-07 / 08-10 实样）：
  - `DaBanList`：`tZhangTing`=涨停、`lZhangTing`=昨涨停、`tFengBan`=封板率、
    `tDieTing`=跌停、`SZJS`=上涨家数、`XDJS`=下跌家数、`PPJS`=炸板、`ZHQD`=综合强度、
    `ZRZTJ`=昨日涨停今收益、`ZRLBJ`=昨连板今收益、`szln`/`qscln` 及 `_zrcs` 系列=两市量能对比
  - `PHBList`：**连板梯队** `[[代码, 名称, 涨幅, ?, "N连板", 板块, "板块;天数"], ...]`
  - `ErBanList`：二板池（同构，盘中为空则午后/尾盘才出）
  - `BaceFaceList`：板块涨幅榜 `[[名称, 涨幅, 板块代码801xxx], ...]`
  - `CWeatherVaneList`：涨/跌风向标个股 `[代码, 名称, 涨跌幅, 板块标签]`
  - `FKYDSixList`：风口异动六股 `[代码, 名称, 涨幅]`（"异动"关键词命中块）

### 2. 资讯流 + 全文 —— 产业新闻→产业链推导原料

```
c=IndexPlate&a=GetIndexList   子域: apparticle   参数: view=1,2,3,4,6 & st=2 & Type=0（列表/分页）
c=ForumsMsgJX&a=GetInfo       子域: apparticle   参数: MsgID=<文章ID> & Tag=1（全文）
```

- 列表：`MsgTop.List[]`：`ID/Title/ZhaiYao/Type/MsgType/CreateTime(unix)/img`
- 全文：`Msg`：`ID/Title/CreateTime/VoteCount/ShareCount/ZhaiYao/Content(HTML)/imgList/Stock[]`
- 实样：「高盛大幅上调PCB/CCL预期」「AI光模块博弈升级 磷化铟战略价值再定价」全文含图片

### 3. 个股

```
c=Stock&a=GetNewOneStockInfo  子域: applhb   参数: StockID & Time=<date> & Type=0
c=Stock&a=GetStockChart       子域: applhb   参数: StockID & Index=0 & st=530（K线，已有 TDX 缓存可不用）
c=Stock&a=GetNewestDay        子域: applhb   参数: StockID（最新交易日）
c=Comments&a=Get              子域: applhb   参数: StockID & Day & Type=1 & st=30（股民评论，噪声大）
```

`GetNewOneStockInfo` 响应：`Name/CurPrice/QuoteChange/TurnoverRatio/Circulation、`
`OnTimeList`=龙虎榜历史上榜日期、`Group.Buy/Sell`=当日龙虎榜席位（上榜日非空）

### 4. 龙虎榜席位（H5 页面同接口）

```
c=Business&a=GetOneBusinessInfo  参数: BusinessID（席位名、Lable 标签）
c=Business&a=PosDoNewStockLog    参数: BusinessID & Day & StockID & LogID & Index & st & SDay & Time & UpNext（操作记录分页）
c=Business&a=GetBusinessChart    参数: BusinessID & Date & StockID & Index & st（胜率曲线）
```

关联页面：`apppage/w47/web/DepkDetails.html?DID=<席位ID>&sid=<股票>&logid=...`

### 5. 游资榜（2026-08-10 盘中捕获；2026-08-11 实测修正）

```
c=UserBusiness&a=GetDay   子域: applhb   参数: Day=YYYY-MM-DD（可选，回溯历史披露日）
```

- `TList`：分类 `[顶级游资(ID=3)/一线游资(2)/知名游资(4)/机构(5)/庄股(1)]`
- `List`：**dict，按分类 ID 分组**（键 `"1"`..`"6"`，值为席位明细数组）——不是扁平数组
- `Day`/`NDay`：数据对应的披露日/上一披露日，`Day` 入参可回溯（实测 2026-08-07/10 均返回对应日）
- **实测：本账号 `List` 各类恒为空**——2026-08-10 抓包样本（Day=2026-08-07）与
  2026-08-11 三次实测（含 Day 回溯）一致。疑席位明细走 App 直连通道（见下节）或需额外权益。
  落盘按 `entry_count=0` + note 标注，不当作异常
- 个股席位明细替代端点（实测可用）：`c=Stock&a=GetNewOneStockInfo`，参数 `StockID`（+`Type=0`），
  返回 `List[].BuyList/SellList`（营业部名称、买卖金额、PX 排名）、`OnTimeList`（历史上榜日）、
  `BuyIn`（净买入）。日榜股票清单端点在代理通道未观察到（疑走直连通道）

### 6. 板块复盘

```
c=ForumsMsgJX&a=GetBkFuPan   （H5 plateReplay.js 中发现，未实测）
```

### 7. 首页/布局/其他

```
c=SysAppVersion&a=GetLaYout   功能宫格布局（含模块 ID 与 H5 外链）
c=Index&a=NewGetList          首页信息流（轮播/广告，闭市 List 为空，无行情价值）
c=StockL2History&a=GetStockTrend  子域: apphis  参数: Day & StockID（历史分时）
c=StockSHGT&a=GetInterviewsByDateJGToStockkLine  （沪深港通/机构调研相关，JS 中发现，未实测）
c=BusinessGroup&a=GetBusinessGroupChart          （席位分组曲线，JS 中发现，未实测）
```

## 第二条通道：直连 + 证书固定（2026-08-10 下午 Reqable VPN 实测）

KPL 包名 `com.aiyu.kaipanla`，官网 `kaipanla.com`（121.37.x，华为云）。
除 longhuvip 系 HTTP API 外，App 还有一组**显式绕过系统代理**（OkHttp NO_PROXY）
且**证书固定**（拒绝用户 CA）的直连通道：

| 端点 | 形态 | 备注 |
|---|---|---|
| `socket.kaipan.com:8080` | HTTPS/TLS socket | 板块/题材实时数据主通道 |
| `hwsockapp.longhuvip.com:17000` | TLS socket | 行情推送 |
| `hwany.longhuvip.com` :443 / :2443 | HTTPS/HTTP | 直连 API |
| `appuser.longhuvip.com` | HTTPS | 用户服务（偶见） |
| 裸 IP 直连 | 113.45.x.x:443、121.14.193.71 等 | 与上面同族（applhb 解析到 113.45.200.207） |

实测结论：

- HTTP 代理模式（mitmproxy）下这些通道**完全不可见**（App 绕过代理直连）；
- VPN 模式（Reqable）下 MITM 被**证书固定**拒绝（CONNECT Aborted、重试风暴）；
- 即使把这两个 socket 域名配成 SSL 绕行（透传），板块/题材详情页在 VPN 下**仍报错**
  （疑 VPN 环境检测或自定义 socket 协议）——**用户级抓包对该通道无解**。
- 因此以下功能的数据**不可得**（除非 root+Frida/重打包，封号风险，不推荐）：
  - **板块/题材详情页**（强度/排名/主力净额、股票池、机构纪要、要闻、小标签页签）
  - **题材库**（早盘"零流量"误判为本地渲染，实为走直连通道）
  - **异动提醒**（另有 MiPush 系统推送通道）
- 注意：**开着 Reqable/mitmproxy 时上述页面不可用**；日常用 App 前确认抓包已停。
- 可用的异动/板块替代数据：`Index.GetInfo` 的 `FKYDSixList`（风口异动）、
  `PHBList`（连板梯队）、`BaceFaceList`（板块涨幅榜）；板块要闻/机构纪要建议改用公开源。

### 待办：异动提醒接口再抓包（2026-08-12 登记，当晚执行）

用户确认 KPL App 内**有**异动提醒功能（盘中异动/严重异动提醒）。2026-08-12 白天排查结论：
代理通道（longhuvip 系 HTTP API）无异动名单接口，`FKYDSixList` 仅 [代码,名称,涨幅] 无阈值字段；
疑走 `socket.kaipan.com:8080` 直连或 MiPush 推送。**晚间行动**：用 Reqable `kpl-api-only`
规则集（仅解密 app*.longhuvip.com）在盘中/复盘时操作 App 异动页签重抓，目标字段：
异动类型、触发阈值、涉及个股代码。若仍走直连 socket 则放弃（不 root/Frida），
regulatory_distance 维持本地计算方案（已实现于 `investment_engine/limit_pool.py`，
口径 `knowledge/wiki/市场分析/A股严重异常波动规则.md`）。抓包结果回填本节。

### Reqable VPN 抓包操作摘要（已配置好，可复用）

1. 手机装 Reqable（小米商店/官网），装其 CA 证书（流程同 mitmproxy CA）。
2. 启动抓包（右下角纸飞机）→ 允许 VPN 连接请求。
3. **关键**：⋮ 菜单 → SSL 代理 → 已建好规则集 `kpl-api-only`（拦截模式，
   仅 `app*.longhuvip.com`）——只解密 API 层，其余透传，App 大部分功能正常
   （板块/题材详情页除外，见上）。已验证 apphwhq API 返回 200 明文。
4. 导出：历史记录 → 导出 HAR。
5. 误判修正：下午抓到的 10jqka/thsi.cn 流量来自**同花顺 App**
   （`com.hexin.plat.android`，后台活跃），与 KPL 无关。

## 受限网络抓包拓扑（公司网拦截场景，2026-08-10 验证）

公司网关行为：放行 API 域名（apphwhq/applhb/apparticle/CDN），
**RST 拦截 `apppage.longhuvip.com`**（H5 容器），apphotfix 被劫持到认证页（503）。
手机直连需过网页认证，且手机自身流量走蜂窝、无法设代理 → 普通 Wi-Fi 代理拓扑失效。

USB + adb 拓扑（手机流量经 USB 隧道进电脑，电脑出口走手机蜂窝）：

```bash
# 0. 一次性准备（已做）：brew install --cask android-platform-tools
#    手机：开发者模式 → USB 调试 → USB 调试（安全设置）（需小米账号/SIM）
# 1. 手机：关 Wi-Fi（纯蜂窝）、开个人热点、插数据线
# 2. 电脑：Wi-Fi 切到手机热点（出口=蜂窝，绕开公司网关）
# 3. 起代理 + 隧道 + 全局代理
mitmdump -p 8080 --set confdir=temp/kpl_capture/mitmconf \
  -w temp/kpl_capture/kpl-flows-<date>.mitm -q
adb reverse tcp:8080 tcp:8080
adb shell settings put global http_proxy 127.0.0.1:8080
# 4. 手机操作 App（链路：App → 127.0.0.1:8080 → adb/USB → mitmdump → 热点蜂窝 → 外网）
# 5. 收尾还原
adb shell settings put global http_proxy :0
adb reverse --remove-all && adb disconnect
# 手机关热点、拔线；电脑 Wi-Fi 切回原网络
```

注意：
- `mitmdump -w` 会**截断同名文件**，重起代理务必换新文件名（mitmdump 12 无追加模式）。
- 开/关「USB 网络共享」会让 adb 瞬断，重跑 `adb devices` 确认即可。
- macOS 原生不支持安卓 USB 网络共享（RNDIS），所以出口走热点而非 USB 共享。
- 手机「USB 调试（安全设置）」用后建议关回。
- adb 远程操控技巧（已验证可用）：`adb shell screencap`+`adb pull` 截图、
  `input tap/swipe/text` 点击输入、`am force-stop`+`monkey` 重启 App、
  `netstat -tne` 按 uid 查 App 直连连接。

## 受限网络抓包拓扑（公司网拦截场景，2026-08-10 验证）

公司网关行为：放行 API 域名（apphwhq/applhb/apparticle/CDN），
**RST 拦截 `apppage.longhuvip.com`**（H5 容器），apphotfix 被劫持到认证页（503）。
手机直连需过网页认证，且手机自身流量走蜂窝、无法设代理 → 普通 Wi-Fi 代理拓扑失效。

USB + adb 拓扑（手机流量经 USB 隧道进电脑，电脑出口走手机蜂窝）：

```bash
# 0. 一次性准备（已做）：brew install --cask android-platform-tools
#    手机：开发者模式 → USB 调试 → USB 调试（安全设置）（需小米账号/SIM）
# 1. 手机：关 Wi-Fi（纯蜂窝）、开个人热点、插数据线
# 2. 电脑：Wi-Fi 切到手机热点（出口=蜂窝，绕开公司网关）
# 3. 起代理 + 隧道 + 全局代理
mitmdump -p 8080 --set confdir=temp/kpl_capture/mitmconf \
  -w temp/kpl_capture/kpl-flows-<date>.mitm -q
adb reverse tcp:8080 tcp:8080
adb shell settings put global http_proxy 127.0.0.1:8080
# 4. 手机操作 App（链路：App → 127.0.0.1:8080 → adb/USB → mitmdump → 热点蜂窝 → 外网）
# 5. 收尾还原
adb shell settings put global http_proxy :0
adb reverse --remove-all && adb disconnect
# 手机关热点、拔线；电脑 Wi-Fi 切回原网络
```

注意：
- `mitmdump -w` 会**截断同名文件**，重起代理务必换新文件名或改用 `+w` 追加。
- 开/关「USB 网络共享」会让 adb 瞬断，重跑 `adb devices` 确认即可。
- macOS 原生不支持安卓 USB 网络共享（RNDIS），所以出口走热点而非 USB 共享。
- 手机「USB 调试（安全设置）」用后建议关回。
