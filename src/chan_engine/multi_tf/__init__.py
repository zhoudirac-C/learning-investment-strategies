"""M7-2 跨周期对齐层（chanlun-m7-multitimeframe-skill.md §5）。

- model：``BiSlice``（笔→切片窗口映射）、``MultiTimeframeChart`` 容器、tf 标签互转；
- aligner：``TFAligner``（日线笔时间窗 → 次级别 bar 切片，时间戳对齐 +
  未收盘 bar 剔除 + coverage 显式传播）、``build_multi_tf_chart`` 装配入口。
"""

from chan_engine.multi_tf.aligner import (
    AlignmentError,
    TFAligner,
    build_multi_tf_chart,
)
from chan_engine.multi_tf.model import (
    BiSlice,
    MultiTimeframeChart,
    tf_label,
    tf_minutes,
)

__all__ = [
    "AlignmentError",
    "BiSlice",
    "MultiTimeframeChart",
    "TFAligner",
    "build_multi_tf_chart",
    "tf_label",
    "tf_minutes",
]
