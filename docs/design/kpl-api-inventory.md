# 开盘啦（KPL）私有 API 接口清单（抓包自 Android App 6.2.20.5，2026-08-09）

> 来源：mitmproxy 抓取本人账号流量整理，仅限个人研究用途，遵守 App 用户协议风险自负。
> 抓包原始文件在 `temp/kpl_capture/`（已 gitignore，含 token，勿外泄）。

## 通用协议

- **入口**：`POST https://<子域>.longhuvip.com/w1/api/index.php?apiv=w47&PhoneOSNew=1&VerSion=6.2.20.5`
- **编码**：`application/x-www-form-urlencoded`，业务参数在 body
- **鉴权**：每个请求 body 必带 `UserID` / `Token`（32 位 hex，登录态）/ `DeviceID`（UUID）
  - token 存 `.env` 的 `kpl_token`（待接入时添加）；失效需重新抓包登录流程
- **业务寻址**：`c=<控制器>&a=<动作>`，响应均为明文 JSON
- **子域即服务划分**：applhb=主服务，apphwhq=行情/情绪，apparticle=资讯，apphis=历史，
  apppage=内嵌 H5，applog=埋点，apphotfix=热更新

## 已验证接口（按系统价值排序）

### 1. 市场情绪/打板大盘 —— 补 M1「涨停池/情绪无缓存」缺口

```
c=Index&a=GetInfo    子域: apphwhq    参数: View=2,3,4,5,7,8,9,10,11
```

响应关键字段（2026-08-07 实样）：

- `DaBanList`：`tZhangTing`=涨停 74、`lZhangTing`=昨涨停 79、`tFengBan`=封板 74、
  `lFengBan`=封板率 79.798、`tDieTing`=跌停 4、`SZJS`=上涨家数 2856、`XDJS`=下跌家数 2536、
  `PPJS`=炸板 143、`ZHQD`=综合强度 63、`ZRZTJ`=昨日涨停今收益 1.258、`ZRLBJ`=昨连板今收益 2.257、
  `szln`/`qscln` 及 `_zrcs` 系列=两市量能与昨日对比
- `BaceFaceList`：板块涨幅榜 `[[名称, 涨幅, 板块代码], ...]`（代码为 801xxx 系）
- `CWeatherVaneList`：`SZ`/`XD` 涨/跌风向标个股 `[代码, 名称, 涨跌幅, 板块标签]`
- `FKYDSixList`：波动最大的六只个股

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

### 5. 板块复盘

```
c=ForumsMsgJX&a=GetBkFuPan   （H5 plateReplay.js 中发现）
```

### 6. 首页/布局/其他

```
c=SysAppVersion&a=GetLaYout   功能宫格布局（含模块 ID 与 H5 外链）
c=Index&a=NewGetList          首页信息流（轮播/广告含研报标题）
c=StockL2History&a=GetStockTrend  子域: apphis  参数: Day & StockID（历史分时）
c=StockSHGT&a=GetInterviewsByDateJGToStockkLine  （沪深港通/机构调研相关，JS 中发现）
c=BusinessGroup&a=GetBusinessGroupChart          （席位分组曲线，JS 中发现）
```

## 未捕获（周日收盘不产生请求，需盘中补抓）

- **题材库**（布局 id=22，原生模块）：积分解锁内容已下载本地，打开不走网络；
  更新/解锁时刻的接口需盘中或重新解锁时抓
- **异动提醒**（id=23）：盘中实时推送类，周日无流量
- **连板梯队实时刷新**：同上，当前只有 DaBanList 的日级汇总
- 机构增仓（H5：`apppage/w47/insPosInc/incPlate.html`）未点

## 盘中补抓操作（交易日 9:30-15:00）

```bash
# 1. 起代理（本仓库根目录）
mitmdump -p 8080 --set confdir=temp/kpl_capture/mitmconf \
  -w temp/kpl_capture/kpl-flows-<date>.mitm -q
# 2. 手机 Wi-Fi 代理指向 192.168.8.9:8080（证书已装过，不用重装）
# 3. 正常用 App：题材库/异动提醒/连板/打板逐个点+滑
# 4. 盘点：mitmdump -nr <flows> -s temp/kpl_capture/inventory2.py --set flow_detail=0 -q
```

注意：`mitmdump -w` 会**截断同名文件**，重起代理务必换新文件名或改用 `+w` 追加。
