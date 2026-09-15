#!/usr/bin/env python3
"""核实：各 UP 的视频类动态分布"""
import glob, re
from collections import defaultdict

stat = defaultdict(lambda: {"视频": [], "其他": 0})
for f in sorted(glob.glob('sources/original/bilibili/*.md')):
    c = open(f, encoding='utf-8').read()
    m_uid = re.search(r'up_uid: "(\d+)"', c)
    m_name = re.search(r'up_name: "([^"]*)"', c)
    m_type = re.search(r'dynamic_type: "([^"]*)"', c)
    m_pub = re.search(r'pub_time: "([^"]*)"', c)
    if not (m_uid and m_type):
        continue
    uid, name, typ = m_uid.group(1), (m_name.group(1) if m_name else '?'), m_type.group(1)
    if typ == "视频":
        # 提取 BV 号
        i = c.find('<!--')
        raw = c[i:] if i > 0 else c
        bv = re.search(r'"bvid":\s*"([^"]+)"', raw)
        dur = re.search(r'"duration_text":\s*"([^"]+)"', raw)
        stat[(uid, name)]["视频"].append({
            'file': f.split('/')[-1][:50],
            'pub': m_pub.group(1) if m_pub else '?',
            'bv': bv.group(1) if bv else '无',
            'dur': dur.group(1) if dur else '?',
        })
    else:
        stat[(uid, name)]["其他"] += 1

print("=" * 78)
print("各 UP 视频类动态统计")
print("=" * 78)
for (uid, name), v in sorted(stat.items(), key=lambda x: -len(x[1]["视频"])):
    print(f"\n【{name}】uid={uid}")
    print(f"  视频: {len(v['视频'])} 条 | 其他类型: {v['其他']} 条")
    for i, r in enumerate(sorted(v['视频'], key=lambda x: x['pub']), 1):
        print(f"    {i:2d}. {r['pub']:<12s} BV={r['bv']:<14s} {r['dur']:>6s}  {r['file']}")

print()
print("=" * 78)
print("汇总")
print("=" * 78)
for (uid, name), v in sorted(stat.items(), key=lambda x: -len(x[1]["视频"])):
    if v["视频"]:
        print(f"  {name}: {len(v['视频'])} 条视频")
