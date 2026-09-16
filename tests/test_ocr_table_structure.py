"""tests for fetch_bilibili_up_v2.ocr_image 表格结构还原（2026-09-16 修复）。

背景：成交单/持仓截图类表格图片，旧实现丢弃 RapidOCR 坐标框（line[0]），
只按识别顺序拼接文本 → 行列关系被交错拍平成一串孤立数字。
修复：① 保留坐标 + 同 y 行聚类 + 行内按 x 排序（` | ` 分隔）；
     ② 水印过滤（box 高 > 中位行高×1.5 → 标 [水印: ...]）。

测试数据 = 2026-09-16 14:05 卢本圆「今日成交单」的真实 OCR 坐标
（1316×746，26 块，实跑 RapidOCR 探针所得）。全部 fake RapidOCR，不触网。
"""

from __future__ import annotations

import sys
import types

import pytest
from PIL import Image

from scripts import fetch_bilibili_up_v2 as fb


def _mk(x0, y0, x1, y1, text, score=0.99):
    """构造 RapidOCR 单行结果：[四点框, 文本, 置信度]。"""
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text, score]


# 2026-09-16 14:05 卢本圆「今日成交单」实拍坐标 (x0, y0, x1, y1, text)
REAL_TRADE_SHEET = [
    (537, 39, 778, 90, "今日成交单"),
    (56, 159, 269, 216, "西点药业"),
    (463, 164, 617, 214, "26.320"),
    (830, 164, 947, 214, "7300"),
    (1153, 160, 1263, 219, "买入"),
    (462, 234, 617, 283, "26.318"),
    (830, 234, 946, 284, "7300"),
    (1154, 228, 1263, 289, "已成"),
    (61, 238, 306, 282, "买14:02:35"),
    (580, 309, 868, 601, "本圆"),  # 跨 3 行的水印/印章
    (56, 353, 269, 411, "西点药业"),
    (463, 359, 625, 407, "26.280"),
    (831, 358, 947, 408, "7600"),
    (1048, 353, 1261, 411, "买入部撤"),
    (463, 425, 618, 478, "26.280"),
    (859, 429, 947, 476, "300"),
    (1150, 420, 1264, 483, "部撤"),
    (61, 432, 305, 475, "买14:02:30"),
    (56, 547, 270, 605, "立新能源"),
    (464, 551, 617, 603, "11.210"),
    (808, 553, 946, 602, "17700"),
    (1154, 546, 1262, 607, "卖出"),
    (61, 625, 307, 670, "卖14:02:24"),
    (466, 623, 617, 672, "11.210"),
    (808, 624, 945, 670, "17700"),
    (1154, 616, 1263, 677, "已成"),
]

EXPECTED_TRADE_SHEET = "\n".join(
    [
        "今日成交单",
        "西点药业 | 26.320 | 7300 | 买入",
        "买14:02:35 | 26.318 | 7300 | 已成",
        "[水印: 本圆]",
        "西点药业 | 26.280 | 7600 | 买入部撤",
        "买14:02:30 | 26.280 | 300 | 部撤",
        "立新能源 | 11.210 | 17700 | 卖出",
        "卖14:02:24 | 11.210 | 17700 | 已成",
    ]
)


@pytest.fixture
def fake_ocr(monkeypatch):
    """monkeypatch RapidOCR，lines 可被测试改写。"""
    holder = {"lines": []}

    class _FakeOCR:
        def __call__(self, img, *a, **k):
            return [list(line) for line in holder["lines"]], None

    fake_mod = types.ModuleType("rapidocr_onnxruntime")
    fake_mod.RapidOCR = _FakeOCR
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake_mod)
    return holder


@pytest.fixture
def tiny_png(tmp_path):
    p = tmp_path / "sheet.png"
    Image.new("RGB", (1316, 746), "white").save(p)
    return p


def test_real_trade_sheet_reconstructed(fake_ocr, tiny_png):
    """回归主用例：真实成交单坐标 → 6 行表格 + 水印单独标注，不再交错拍平。"""
    fake_ocr["lines"] = [_mk(*b) for b in REAL_TRADE_SHEET]
    assert fb.ocr_image(tiny_png) == EXPECTED_TRADE_SHEET


def test_row_order_by_x_within_row(fake_ocr, tiny_png):
    """同一视觉行内的块按 x 排序，即使 OCR 返回顺序打乱。"""
    fake_ocr["lines"] = [_mk(200, 10, 260, 40, "B"), _mk(50, 12, 120, 38, "A")]
    assert fb.ocr_image(tiny_png) == "A | B"


def test_separate_rows_for_distant_y(fake_ocr, tiny_png):
    fake_ocr["lines"] = [_mk(50, 10, 120, 40, "A"), _mk(50, 100, 120, 130, "B")]
    assert fb.ocr_image(tiny_png) == "A\nB"


def test_watermark_flagged_not_in_table(fake_ocr, tiny_png):
    """高 > 中位行高×1.5 的块 → [水印: ...]，不混进数据行。"""
    fake_ocr["lines"] = [
        _mk(50, 10, 120, 60, "正常行一"),
        _mk(580, 100, 868, 400, "本圆"),  # 高 300 ≫ 中位 50
        _mk(50, 110, 120, 160, "正常行二"),
    ]
    out = fb.ocr_image(tiny_png).splitlines()
    assert "[水印: 本圆]" in out
    assert all(line == "[水印: 本圆]" or "本圆" not in line for line in out)


def test_empty_result_returns_empty(fake_ocr, tiny_png):
    fake_ocr["lines"] = []
    assert fb.ocr_image(tiny_png) == ""


def test_group_rows_pure_function():
    boxes = [
        {"text": "B", "x0": 200, "y0": 10, "x1": 260, "y1": 40},
        {"text": "A", "x0": 50, "y0": 12, "x1": 120, "y1": 38},
    ]
    rows = fb._group_rows(boxes)
    assert [[b["text"] for b in row] for row in rows] == [["A", "B"]]


def test_filter_watermarks_pure_function():
    boxes = [
        {"text": "n", "x0": 0, "y0": 0, "x1": 70, "y1": 50},
        {"text": "stamp", "x0": 580, "y0": 309, "x1": 868, "y1": 601},
        {"text": "m", "x0": 0, "y0": 100, "x1": 70, "y1": 150},
    ]
    normal, marks = fb._filter_watermarks(boxes)
    assert [b["text"] for b in normal] == ["n", "m"]
    assert [b["text"] for b in marks] == ["stamp"]
