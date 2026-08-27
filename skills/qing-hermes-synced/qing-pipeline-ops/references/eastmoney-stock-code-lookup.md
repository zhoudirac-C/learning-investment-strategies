# 东方财富股票代码查询 — URL 编码陷阱

## 问题（2026-08-05 实测）

`searchapi.eastmoney.com/api/suggest/get` 的 `input` 参数**必须 URL 编码**。
中文直传 → 返回 `HTTP 400 Bad Request`（空 HTML 错误页），不是 JSON。

```bash
# ❌ 错误：中文直传 → HTTP 400
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=传智教育&type=14&count=1"
# → <!doctype html>...HTTP Status 400 – Bad Request...

# ✅ 正确：先 URL 编码
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=%E4%BC%A0%E6%99%BA%E6%95%99%E8%82%B2&type=14&count=1"
```

## 正确用法

```bash
# 单条查询（内联编码）
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=$(python3 -c 'import urllib.parse; print(urllib.parse.quote("公司名"))')&type=14&count=1" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['QuotationCodeTable']['Data'][0]['Code'], d['QuotationCodeTable']['Data'][0]['SecurityTypeName'])"

# 批量查询（Step 2 补代码时常用）：
for name in 传智教育 茂莱光学 中际旭创; do
  enc=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$name'))")
  result=$(curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=$enc&type=14&count=1" --max-time 10 | \
    python3 -c "import sys,json; d=json.load(sys.stdin); ds=d.get('QuotationCodeTable',{}).get('Data') or []; print(f\"{ds[0]['Code']}|{ds[0]['SecurityTypeName']}|{ds[0]['Name']}\" if ds else 'NOTFOUND')")
  echo "$name => $result"
done
```

## 返回字段

```json
{"QuotationCodeTable": {"Data": [{
  "Code": "003032",          // 6位代码
  "Name": "传智教育",
  "SecurityTypeName": "深A", // 深A/沪A/创业板/科创板
  "SecurityType": "2"
}]}}
```

- `SecurityTypeName` 用于标注板块：深A/沪A=主板可交易，创业板/科创板=不可交易（role 中标注）
- 查不到时 `Data` 为空列表 → 输出 NOTFOUND，检查名字是否准确（如"行云科技"查得到、"行云"查不到）

## 关联

- 这是 `qing-learning-claim` SKILL.md「股票代码查询」一节的实操修正
  （该 skill 位于 project external dir，只读，修正记录在此）
- Step 2 补代码场景：statement/interpretation 中每家公司标 `公司名(6位代码)`，
  related_stocks 的 `code` 必须为带引号字符串（前导零保留）
