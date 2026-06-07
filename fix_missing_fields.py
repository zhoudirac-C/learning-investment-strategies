#!/usr/bin/env python3
"""Fix missing fields across all YAML claim files using ruamel.yaml for round-trip preservation."""
import glob, os, re
from ruamel.yaml import YAML

yaml_rt = YAML()
yaml_rt.preserve_quotes = True
yaml_rt.indent(mapping=4, sequence=4, offset=2)
yaml_rt.width = 200

CLAIM_DIR = 'knowledge/claims'
files = sorted(glob.glob(f'{CLAIM_DIR}/*.yaml'))

def insert_at(c, key, value, after_key=None, before_key=None):
    """Insert key:value into ruamel CommentedMap. Returns True if inserted."""
    if key in c:
        return False
    keys = list(c.keys())
    pos = len(keys)
    if after_key is not None and after_key in keys:
        pos = keys.index(after_key) + 1
    elif before_key is not None and before_key in keys:
        pos = keys.index(before_key)
    c.insert(pos, key, value)
    return True

def generate_tags(subject, statement):
    """Generate tags from subject and statement keywords."""
    key_map = {
        '储能': ['储能', '锂电', '电池', '标的清单'],
        '消费': ['消费', '消费品', '标的清单'],
        '蓝筹/传统': ['蓝筹', '传统行业', '标的清单'],
        '蓝筹防御': ['蓝筹', '防御配置', '电力', '医药'],
        '新能源装备': ['新能源', '电力设备', '标的清单'],
        '航运': ['航运', '周期', '标的清单'],
        '美股暴跌': ['美股', '全球市场', '博通', '情绪冲击'],
        '当前市场阶段': ['市场阶段', '黄金坑', '调整'],
        '科技/AI': ['科技', 'AI硬件', '清仓', '补跌'],
        '磨底期': ['磨底期', '方向切换', '机器人', '商业航天'],
        'CPI': ['CPI', '宏观变量', '通胀'],
        '原油': ['原油', '宏观风险', '连锁反应'],
        '黄金': ['黄金', '避险', '目标位'],
        '润泽': ['润泽科技', '数据中心', '补跌风险'],
        '算力租赁': ['算力租赁', 'B300', '稀缺性'],
        '新闻联播': ['政策信号', '新闻联播', '托底'],
        '领涨龙头': ['吹哨人', '方法论', '领涨龙头'],
    }
    for k, v in key_map.items():
        if k in subject:
            return v[:6]
    return ['标的清单']

changes = []

for fpath in files:
    fname = os.path.basename(fpath)
    
    with open(fpath, 'r') as f:
        data = yaml_rt.load(f)
    
    if data is None:
        print(f'EMPTY: {fname}')
        continue
    
    # Determine format
    if isinstance(data, dict) and 'claims' in data:
        claims = data['claims']
        if not isinstance(claims, list):
            claims = [claims]
            data['claims'] = claims
    elif isinstance(data, list):
        claims = data
    elif isinstance(data, dict):
        claims = [data]
    else:
        print(f'UNKNOWN FORMAT: {fname}: {type(data)}')
        continue
    
    modified = False
    
    for i, c in enumerate(claims):
        if not isinstance(c, dict):
            continue
        cid = c.get('id', f'UNKNOWN-{i}')
        
        # Fix missing topic (after subject)
        if 'topic' not in c:
            subject = c.get('subject', '')
            insert_at(c, 'topic', subject, after_key='subject')
            print(f'  +topic: {fname}[{i}] id={cid}')
            modified = True
        
        # Fix missing tags (before supersedes/contradicts, else after status)
        if 'tags' not in c:
            subject = c.get('subject', '')
            statement = c.get('statement', c.get('text', ''))
            tag_list = generate_tags(subject, statement)
            if 'supersedes' in c:
                insert_at(c, 'tags', tag_list, before_key='supersedes')
            elif 'contradicts' in c:
                insert_at(c, 'tags', tag_list, before_key='contradicts')
            elif 'related_claims' in c:
                insert_at(c, 'tags', tag_list, after_key='related_claims')
            else:
                insert_at(c, 'tags', tag_list, after_key='status')
            print(f'  +tags: {fname}[{i}] id={cid} -> {tag_list}')
            modified = True
        
        # Fix missing links (after contradicts, supersedes, or at end)
        if 'links' not in c:
            if 'contradicts' in c:
                insert_at(c, 'links', {}, after_key='contradicts')
            elif 'supersedes' in c:
                insert_at(c, 'links', {}, after_key='supersedes')
            else:
                insert_at(c, 'links', {}, after_key='status')
            print(f'  +links: {fname}[{i}] id={cid}')
            modified = True
        
        # Fix missing source fields
        if 'subject' not in c:
            insert_at(c, 'subject', c.get('topic', ''), after_key='topic')
            print(f'  +subject: {fname}[{i}] id={cid}')
            modified = True
        
        if 'source_type' not in c:
            sp = c.get('source_path', '')
            if '视频' in sp:
                ct = '视频'
            elif '动态' in sp:
                ct = '动态'
            elif '早盘' in sp:
                ct = '早盘'
            elif '周复盘' in sp:
                ct = '周复盘'
            else:
                ct = ''
            insert_at(c, 'source_type', ct, after_key='source_path')
            print(f'  +source_type: {fname}[{i}] id={cid} -> "{ct}"')
            modified = True
        
        if 'source_date' not in c:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
            sd = date_match.group(1) if date_match else ''
            insert_at(c, 'source_date', sd, after_key='source_type')
            print(f'  +source_date: {fname}[{i}] id={cid} -> "{sd}"')
            modified = True
        
        if 'extracted_at' not in c:
            insert_at(c, 'extracted_at', c.get('source_date', ''), after_key='source_date')
            print(f'  +extracted_at: {fname}[{i}] id={cid}')
            modified = True
        
        if 'source_path' not in c:
            if 'source_type' in c:
                insert_at(c, 'source_path', '', before_key='source_type')
            elif 'source_date' in c:
                insert_at(c, 'source_path', '', before_key='source_date')
            else:
                insert_at(c, 'source_path', '', after_key='id')
            print(f'  +source_path: {fname}[{i}] id={cid}')
            modified = True
        
        # Fix missing statement (for claim-20260604-001.yaml which has 'text' but no 'statement')
        if 'statement' not in c and 'text' in c:
            insert_at(c, 'statement', c['text'], after_key='text')
            print(f'  +statement: {fname}[{i}] id={cid} (from text)')
            modified = True
    
    if modified:
        with open(fpath, 'w') as f:
            yaml_rt.dump(data, f)
        changes.append(fname)
        print(f'  WROTE: {fname}')

print(f'\n=== SUMMARY ===')
print(f'Files modified: {len(changes)}')
for c in changes:
    print(f'  {c}')
print('Done.')
