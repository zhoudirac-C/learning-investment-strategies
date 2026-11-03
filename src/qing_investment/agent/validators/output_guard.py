from __future__ import annotations

import re
from datetime import datetime


_HALLUCINATION_FUTURE_YEAR = re.compile(r"20(2[7-9]|[3-9]\d)年")
_HALLUCINATION_META = re.compile(r"数据恢复是最关键")
_HALLUCINATION_DATE_REVIEW = re.compile(r"这是(20\d{2})年(\d{1,2})月(\d{1,2})日(盘后)?复盘")


def is_hallucinated_output(output: str) -> bool:
    if _HALLUCINATION_FUTURE_YEAR.search(output):
        return True
    if _HALLUCINATION_META.search(output):
        return True
    current_year = datetime.now().year
    for match in _HALLUCINATION_DATE_REVIEW.finditer(output):
        try:
            if int(match.group(1)) > current_year:
                return True
        except ValueError:
            pass
    return False
