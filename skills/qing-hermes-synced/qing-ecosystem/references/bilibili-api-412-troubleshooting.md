# B站 API 412 Precondition Failed 诊断与恢复

## 问题现象

`scripts/fetch_bilibili_up_v2.py` 运行时无声超时（exit code 124），不输出任何内容。
`urllib.request.urlopen()` 底层抛出 `HTTPError 412`，但脚本主循环未捕获该异常。

## 根因

B站（2026年中）升级了动态 feed API 的反爬机制，只携带 SESSDATA 的裸请求会被返回 412。但 `fetch_bilibili_up_v2.py` 的 `build_cookie()` 函数会拼装包含 buvid3、b_lsid、buvid4、sid 等 20+ 字段的完整 Cookie 模板——B站反爬校验了这些字段的关联性，**完整的 Cookie 模板足以通过 412 检查**，不需要 wbi 签名。

**重要：fetch_bilibili_up_v2.py 实际上能正常工作。** 2026年7月29日的实测中，`fetch_bilibili_up_v2.py --uid 1420210197 --sessdata "$(cat ~/.hermes/bilibili_sessdata.txt)"` 顺利拉取了多条新的充电专属动态，未遇到 412。此前诊断中遇到的 412 都是因为用 curl 单独传 SESSDATA 测试——这本身就会触发反爬，不代表脚本不可用。始终通过 fetch_bilibili_up_v2.py 运行，不要用 curl 测试 SESSDATA 有效性。

### 受影响的范围

| 端点 | 状态 | 说明 |
|------|------|------|
| `/x/polymer/web-dynamic/v1/feed/space` | ⚠️ 仅完整Cookie模板可用 | 裸请求412；通过`fetch_bilibili_up_v2.py`的`build_cookie()`全模板正常 |
| `/x/polymer/web-dynamic/v1/detail?id=...` | ❌ 4101152 | 即使登录，充电专属内容也返回"动态不可见" |
| `/x/article/viewinfo?id=...` | ❌ -404 | 专栏 API 完全封锁（"啥都木有"） |
| `/x/space/arc/search` | ✅ 正常 | 视频列表，移动 UA 可用 |
| `/x/web-interface/nav` | ✅ 正常 | 登录验证，不受影响 |
| `/x/space/wbi/arc/search` | ❌ -403 | wbi 签名版也失败（"访问权限不足"） |

## 诊断命令集

```bash
# 1. 验证 SESSDATA 有效性
SESSDATA=$(cat ~/.hermes/bilibili_sessdata.txt)
curl -s --max-time 10 \
  -H "User-Agent: Mozilla/5.0" \
  -H "Cookie: SESSDATA=${SESSDATA}" \
  "https://api.bilibili.com/x/web-interface/nav" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Login: {d[\"data\"][\"isLogin\"]}, Name: {d[\"data\"][\"uname\"]}')"

# 2. 测试动态 feed（应得 412）
curl -s -o /tmp/bili_test.txt -w "HTTP:%{http_code}" --max-time 10 \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  -H "Cookie: SESSDATA=${SESSDATA}" \
  -H "Referer: https://space.bilibili.com/1420210197/dynamic" \
  "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid=1420210197&timezone_offset=-480"
cat /tmp/bili_test.txt | head -c 300

# 3. 测试视频列表（应正常）
curl -s --max-time 10 \
  -H "User-Agent: Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36" \
  -H "Cookie: SESSDATA=${SESSDATA}" \
  "https://api.bilibili.com/x/space/arc/search?mid=1420210197&ps=5&pn=1" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  {v[\"title\"]}') for v in d.get('data',{}).get('list',{}).get('vlist',[])]"
```

## 恢复方案

### P0：用户手动粘贴内容（最快）

请求用户从 B站 APP 复制复盘/专栏文字内容直接发给微信，Agent 直接提取 claims。
不需要经过 fetch 脚本。

### P1：QR 扫码刷新 SESSDATA

有两套脚本可选：

**方案 A（原始，单次）：** `scripts/bilibili_qr_login.py`
```bash
cd ~/learning-investment-strategies
uv run python scripts/bilibili_qr_login.py --output ~/.hermes/bilibili_sessdata.txt
```
- 单次运行，二维码超时需手动重启

**方案 B（推荐 — 自动刷新）：** `scripts/qr_login_auto.py`
```bash
cd /home/ubuntu/.hermes/skills/qing/qing-ecosystem
python3 scripts/qr_login_auto.py
```
- 二维码过期自动重新生成并输出新的 MEDIA:path
- 登录成功后自动保存 SESSDATA 并退出
- SESSDATA 提取失败时打印完整 API 响应用于调试
- 无需手动重启

**⚠️ 关键流程：用户需要「扫码 + 手机上确认」两步**

脚本输出 `已扫码，请在手机上确认登录...` 时，用户必须在手机B站APP上点击 **「确认登录」** 按钮，才算完成。仅扫码不确认会导致脚本最终超时退出。

#### QR 登录常见问题

| 现象 | 可能原因 | 处理方式 |
|------|----------|---------|
| 脚本提示 `登录成功但未获取到SESSDATA` | B站 QR poll API 返回了 status=0 但 `cookie_info.cookies` 为空或格式变更 | 使用方案 B（自动刷新脚本），失败时会打印完整 API 响应到 stderr；检查 `data.cookie_info.cookies` 是否存在且包含 SESSDATA |
| 用户反复说"再发一次" | 二维码超时（默认 180s），旧脚本需手动重启 | 改用方案 B（自动刷新脚本），过期自动重发 |
| 扫码后脚本未提示"已扫码" | 网络问题或 B站 API 限流 | 检查网络，等待 2s 自动重试 |
| `二维码已失效` | 二维码超出有效期 | 方案 B 会自动刷新；方案 A 需重新运行 |
| 刷新 SESSDATA 后 fetch 仍失败 | SESSDATA 与 412 无关（反爬机制问题） | 见下文「QR 登录后 fetch 仍失败的处理」 |

**注意**：即使刷新了 SESSDATA，用 curl 单独传 SESSDATA 测试 feed API 仍会返回 412（因为缺少完整 Cookie 模板）。这**不等于 fetch 脚本不可用**——始终通过 `fetch_bilibili_up_v2.py --sessdata "..."` 运行，不要用 curl 裸测。

#### QR 登录后 fetch 仍失败的处理

如果 QR 登录成功（SESSDATA 有效），但 fetch 脚本仍因 412 无声超时：

1. **确认是否用完整脚本运行**：不要用 curl 测试，直接用 `fetch_bilibili_up_v2.py --sessdata "..."` 运行
2. **确认 SESSDATA 有效**：用 nav API 验证（见上方诊断命令集）
3. **检查脚本超时**：默认 timeout=15s，网络慢时可尝试增加至 30s
4. **排查 fetch 脚本**：检查 `fetch_dynamic_list()` 是否捕获了 HTTPError 412，或卡在 `urlopen()` 等待
5. **走 P0 方案**（用户手动粘贴内容）作为最终兜底

### P2：修复 fetch 脚本（增强健壮性）

当前脚本通过完整 Cookie 模板已能正常拉取，以下修改可进一步提升健壮性：

1. **添加 412 错误处理**：在 `fetch_dynamic_list()` 中捕获 `HTTPError`，当 code=412 时输出诊断信息而非静默超时
2. **增加超时**：当前 timeout=15s，对于 B站 海外 CDN 可放宽至 30s
3. **备用端点**：当 feed/space 失败时，尝试回退到其他端点（如 `x/space/arc/search` 获取视频+专栏列表）

```python
# 伪代码：412 错误处理
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    if e.code == 412:
        print(f"ERROR: B站 API 412 Precondition Failed", file=sys.stderr)
        print(f"提示：B站反爬机制升级，需 wbi 签名或手动更新 fetch 脚本", file=sys.stderr)
        # 尝试备用端点
        return fetch_via_backup_endpoint(uid, sessdata)
    raise
```

## 判断下游数据完整性

当 fetch 脚本失败后，需要确认本地已有什么、缺什么：

```bash
# 查看最近抓取文件
ls -lt ~/learning-investment-strategies/sources/original/bilibili/*.md | head -10

# 查看状态文件中的 last_check_time
cat ~/.hermes/bilibili_up_state.json | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'Last check: {d[\"last_check_time\"]}, Last ID: {d[\"last_dynamic_id\"]}')"

# 对比 UP 实际发布时间线
# 从视频 API 获取 UP 最近的视频时间作为参照
SESSDATA=$(cat ~/.hermes/bilibili_sessdata.txt)
curl -s --max-time 10 \
  -H "User-Agent: Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Mobile" \
  -H "Cookie: SESSDATA=${SESSDATA}" \
  "https://api.bilibili.com/x/space/arc/search?mid=1420210197&ps=5&pn=1" \
  | python3 -c "import sys,json; from datetime import datetime; d=json.load(sys.stdin); [print(f'{datetime.fromtimestamp(v[\"created\"]).strftime(\"%m-%d %H:%M\")} {v[\"title\"]}') for v in d['data']['list']['vlist']]"
```
