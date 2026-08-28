"""M7-3 G7：MACD 计算（纯函数，零依赖）。

口径（chanlun-m7-multitimeframe-skill.md §7.2，v1.3 改判）：MACD 柱面积为
背驰**主口径**（与 UP 课程 P2/P4 及 skill 现行纪律一致），Σ|Δc| 降为校准对照。

实现与 skill ``chan_analysis.py`` 的 ``calc_macd`` 逐位一致：

- EMA12/26/9，**首值用首根 close 做种子**（ema_f[0]=ema_s[0]=close[0]，
  dea[0]=dif[0]=0，故 hist[0]=0）；
- 无预热丢弃：短序列可直接用，但前几根 hist 受种子影响（预热效应）——
  调用方对长序列前缀的背驰结论应知悉此口径（skill 同行为，不改）。
"""
from __future__ import annotations


def calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float], list[float], list[float]]:
    """收盘价序列 → (dif, dea, hist)。等长输出；hist = (dif - dea) * 2。"""
    n = len(closes)
    ema_f = [0.0] * n
    ema_s = [0.0] * n
    dif = [0.0] * n
    dea = [0.0] * n
    hist = [0.0] * n
    kf, ks, kd = 2 / (fast + 1), 2 / (slow + 1), 2 / (signal + 1)
    for i in range(n):
        c = float(closes[i])
        ema_f[i] = c if i == 0 else c * kf + ema_f[i - 1] * (1 - kf)
        ema_s[i] = c if i == 0 else c * ks + ema_s[i - 1] * (1 - ks)
        dif[i] = ema_f[i] - ema_s[i]
        dea[i] = dif[i] if i == 0 else dif[i] * kd + dea[i - 1] * (1 - kd)
        hist[i] = (dif[i] - dea[i]) * 2
    return dif, dea, hist
