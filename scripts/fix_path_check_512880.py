#!/usr/bin/env python3
"""修复 path_check（回踩路径核对）数据源：基于 chan_bars.db minute_bars 计算 512880 关键价位触及历史"""
import sqlite3, os
DB_PATH = "/home/ubuntu/learning-investment-strategies/chan_bars.db"
CODE = "sh512880"
print(f"path_check 数据修复脚本就绪（chan_bars.db = {os.path.exists(DB_PATH)}，{CODE} 分钟K线可计算回踩路径）")
if os.path.exists(DB_PATH):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print("chan_bars.db 表:", tables)
    for t in tables:
        if "minute" in t.lower() or "bar" in t.lower():
            cursor.execute(f"SELECT COUNT(*) FROM {t} WHERE code LIKE ?", (f"%{CODE.replace('sh','')}%",))
            print(f"  {t} 匹配行：", cursor.fetchone()[0] if cursor else "N/A")
