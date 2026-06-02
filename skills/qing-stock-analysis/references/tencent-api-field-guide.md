# 腾讯财经 API (qt.gtimg.cn) 字段解析参考

## 接口地址

```
https://qt.gtimg.cn/q=sz000969,sz000066,sh600519
```

- 深市前缀 `sz`，沪市前缀 `sh`
- 多个代码用逗号分隔
- 返回 GBK 编码，需 `iconv -f gbk -t utf-8` 转换

## 响应格式

每只股票一行，以分号结尾：

```
v_sz000969="51~安泰科技~000969~21.83~22.51~22.39~...~20260602112927~-0.68~-3.02~22.73~21.49~...";
```

## 关键字段（按名称定位，避免硬编码索引）

| 字段 | 说明 | 定位方式 |
|------|------|----------|
| 股票名称 | 安泰科技 | `split('~')[1]` |
| 股票代码 | 000969 | `split('~')[2]` |
| 最新价 | 21.83 | `split('~')[3]` |
| 昨收 | 22.51 | `split('~')[4]` |
| 开盘价 | 22.39 | `split('~')[5]` |
| 时间戳 | 20260602112927 | 查找 `^[0-9]{14}$` 格式的字段 |
| 涨跌额 | -0.68 | 时间戳后第2个字段（动态） |
| 涨跌幅 | -3.02 | 时间戳后第3个字段（动态） |
| 最高价 | 22.73 | 时间戳后第4个字段（动态） |
| 最低价 | 21.49 | 时间戳后第5个字段（动态） |

## 陷阱：字段索引漂移

不同股票的买卖盘深度不同，导致 `split('~')` 后的总字段数不同。

**错误做法（硬编码索引）**：
```bash
# 不要这样做！不同股票 a[32]/a[34] 含义不同
curl -s 'https://qt.gtimg.cn/q=sz000969' | awk -F'~' '{print $32}'
```

**正确做法1：手动计算涨跌幅（推荐）**
```bash
curl -s 'https://qt.gtimg.cn/q=sz000969' | iconv -f gbk -t utf-8 | \
  awk -F'~' '{printf "%.2f%%\n", ($4-$5)/$5*100}'
```

**正确做法2：动态定位时间戳后字段**
```bash
curl -s 'https://qt.gtimg.cn/q=sz000969' | iconv -f gbk -t utf-8 | \
  awk -F'~' '{
    for(i=1;i<=NF;i++) if($i ~ /^[0-9]{14}$/) {ts=i; break}
    print "涨跌幅="$(ts+3)"%"
  }'
```

**正确做法3：Python 解析（最稳健）**
```python
import urllib.request, re

url = 'https://qt.gtimg.cn/q=sz000969,sz000066'
with urllib.request.urlopen(url, timeout=10) as r:
    data = r.read().decode('gbk')

for line in data.strip().split(';'):
    if not line.strip(): continue
    m = re.search(r'v_(\w+)="([^"]+)"', line)
    if m:
        parts = m.group(2).split('~')
        name = parts[1]
        latest = float(parts[3])
        prev = float(parts[4])
        pct = (latest - prev) / prev * 100
        print(f'{name} 最新={latest} 涨跌幅={pct:.2f}%')
```

## 常用提取命令

```bash
# 单只：最新价+涨跌幅（手动计算）
curl -s 'https://qt.gtimg.cn/q=sz000969' | iconv -f gbk -t utf-8 | \
  awk -F'~' '{print $2, $3, "最新="$4, "涨跌幅="($4-$5)/$5*100"%"}'

# 多只：批量提取
codes="sz000969,sz000066,sh600519"
curl -s "https://qt.gtimg.cn/q=$codes" | iconv -f gbk -t utf-8 | tr ';' '\n' | \
  grep 'v_' | awk -F'"' '{split($2,a,"~"); print a[2], a[3], "最新="a[4], "涨跌幅="(a[4]-a[5])/a[5]*100"%"}'
```

## 参考

- 腾讯财经 API 非官方文档，字段结构可能变更
- 当手动计算与 API 返回的涨跌幅不一致时，以手动计算为准（基于昨收）
- 监控脚本 `stock_monitor.py` 内部使用 Python `requests` + 正则解析，逻辑与上述 Python 示例一致
