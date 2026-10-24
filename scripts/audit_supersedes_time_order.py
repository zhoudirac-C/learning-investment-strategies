"""反向边审计：扫描全部 claim YAML，找出 supersedes 方向违例的边。
supersedes 语义 = 「源取代目标」= 源应新于（或同于）目标。
源 source_date < 目标 source_date 即「历史观点替代最近观点」违例。"""
import glob
import json
import sys

import yaml

id2date = {}
edges = []
n_files = 0
for f in sorted(glob.glob('knowledge/claims/*.yaml')):
    try:
        data = yaml.safe_load(open(f, encoding='utf-8'))
    except Exception as e:
        print('PARSE-ERR', f, e)
        continue
    if data is None:
        continue
    n_files += 1
    if isinstance(data, list):
        claims = [c for c in data if isinstance(c, dict)]
    elif isinstance(data, dict):
        claims = data.get('claims') if 'claims' in data else [data]
        if not isinstance(claims, list):
            claims = [claims]
    else:
        continue
    for c in claims:
        if not isinstance(c, dict) or not c.get('id'):
            continue
        cid = c['id']
        id2date[cid] = str(c.get('source_date') or '')
        for tgt in (c.get('supersedes') or []):
            edges.append((cid, str(tgt), f))

backwards = []
missing_tgt = 0
for src, tgt, f in edges:
    d_src, d_tgt = id2date.get(src, ''), id2date.get(tgt, '')
    if not d_tgt:
        missing_tgt += 1
        continue
    if d_src and d_tgt and d_src < d_tgt:
        backwards.append({'src': src, 'src_date': d_src,
                          'tgt': tgt, 'tgt_date': d_tgt, 'file': f})

print(f'files={n_files} claims={len(id2date)} supersedes_edges={len(edges)}')
print(f'目标缺失={missing_tgt} 反向违例={len(backwards)}')
for b in backwards:
    print(json.dumps(b, ensure_ascii=False))
