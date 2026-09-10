#!/usr/bin/env python3
"""全量扫描 TDX host 目录：TCP 连通性 + K线实际取数。"""
import sys, time, socket, json
sys.path.insert(0, "src")

from concurrent.futures import ThreadPoolExecutor, as_completed
from qing_investment.tdx_market.hosts import DefaultHostCatalog, HostCapability

KL_CAP = HostCapability.CapMainKline

def tcp_check(ip, port, t=4):
    try:
        s = socket.create_connection((ip, port), timeout=t)
        s.close()
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}"

def kline_check(ip, port, kind):
    """kind: 'pytdx' for 7709 std; 'ex' skipped (港股协议)"""
    from pytdx.hq import TdxHq_API
    api = TdxHq_API(heartbeat=False)
    try:
        if not api.connect(ip, port, time_out=5):
            return None, "connect_false"
        d = api.get_security_bars(9, 1, "000001", 0, 5)   # 上证指数 日线
        n = len(d) if d else 0
        api.disconnect()
        return n, None
    except Exception as e:
        try: api.disconnect()
        except Exception: pass
        return None, f"{type(e).__name__}:{str(e)[:40]}"

hosts = DefaultHostCatalog
targets = [h for h in hosts if (h.Capabilities & KL_CAP)]
print(f"目录总计 {len(hosts)} 个 host；具备 A股K线能力(CapMainKline)的 {len(targets)} 个\n")

results = []
def probe(h):
    t0 = time.time()
    tcp_ok, tcp_err = tcp_check(h.IP, h.Port)
    kl, kl_err = (None, "tcp_fail") if not tcp_ok else kline_check(h.IP, h.Port, "main")
    ok = (kl or 0) > 0
    return {
        "name": h.Name, "ip": h.IP, "port": h.Port, "enabled": h.Enabled,
        "weight": getattr(h, "Weight", None), "tcp": tcp_ok, "tcp_err": tcp_err,
        "kline_bars": kl, "kline_err": kl_err, "ok": ok, "ms": int((time.time()-t0)*1000),
    }

with ThreadPoolExecutor(max_workers=16) as ex:
    futs = {ex.submit(probe, h): h for h in targets}
    for f in as_completed(futs):
        try: results.append(f.result())
        except Exception as e: print("probe crash:", e)

order = {"tcp_fail": 0, "connect_false": 1, "kline_zero": 2, "ok": 3}
def rank(r):
    if not r["tcp"]: k=0
    elif (r["kline_bars"] or 0) > 0: k=3
    elif r["kline_bars"] == 0: k=2
    else: k=1
    return (k, r["name"])

results.sort(key=rank, reverse=True)

print(f"{'状态':6} {'名称':16} {'IP':18} {'端口':6} {'EN':4} {'K线':5} {'耗时':6} 备注")
print("-"*92)
for r in results:
    if (r["kline_bars"] or 0) > 0:
        st = "✅可用"
    elif r["kline_bars"] == 0:
        st = "⚠️空数据"
    elif r["tcp"]:
        st = "⚠️协议错"
    else:
        st = "❌不通"
    note = r["kline_err"] or r["tcp_err"] or ""
    print(f"{st:6} {r['name']:16} {r['ip']:18} {r['port']:<6} {str(r['enabled'])[:3]:4} {str(r['kline_bars']):5} {r['ms']:>5}ms {note}")

good = [r for r in results if r["ok"] and r["enabled"]]
good_dis = [r for r in results if r["ok"] and not r["enabled"]]
print("\n" + "="*92)
print(f"可用(enabled)          : {len(good)}")
for r in good: print(f"   ✅ {r['name']:16} {r['ip']}:{r['port']}")
print(f"可用但已被禁用(Enabled=False): {len(good_dis)}")
for r in good_dis: print(f"   ✅ {r['name']:16} {r['ip']}:{r['port']}")

json.dump(results, open("/tmp/tdx_scan.json","w"), ensure_ascii=False, indent=1)
print("\n完整结果 -> /tmp/tdx_scan.json")
