# 缠论教学图绘制配方（matplotlib，2026-08-26 验证有效）

用户偏好：缠论概念纯文字讲解不够，必须配图。已产出验证过的图：
- 512400 中枢严格口径图（`/tmp/chan_zhongshu_512400_v2.png`）
- P4 背驰四面板图（`/tmp/chan_p4_lecture_v2.png` + 面板3放大 `/tmp/chan_p4_panel3_final.png`）
- P6 分型笔线段五面板图（`/tmp/chan_p6_lecture_v2.png`）

## 强制自检流程（v1教训：未自检直接发图被抓出两处实错）

1. 画完必须 vision_analyze 自检：标注是否压标题/互相叠压/越界、箭头指向是否准确（尤其双轴图）、中枢矩形是否框对区间
2. 按问题清单逐项修复 → 重出 v2 → 再自检
3. vision 服务限流(429)时 sleep 90-180s 重试最多2轮；仍失败则如实告知"未经视觉复核"，勿声称已检查

## 布局防叠压要点（v1实错总结）

- annotate 的 xytext 用数据坐标时，必须 set_ylim 扩大上限留白，否则文字挤出轴区压到标题
- 概念面板(axis off)文字框之间要拉开 y 间距，勿共用同一水平带
- 双轴箭头指向另一轴的高点需换算：`to_ax(y) = ylo + (y-plo)/(phi-plo)*(yhi-ylo)`——v1 曾因未换算把箭头指到 0 轴附近
- 面积演示用 axvspan 底色带标出笔区间 + 白底 bbox 标注框（alpha 0.9）隔离背景柱体

## 模式：多面板 = 概念(合成数据) + 实战(真实数据)

1. **概念面板**：合成随机游走数据（random.Random(seed) 固定种子）画出理想结构（如 A-B-C 背驰、中枢震荡），矩形框标注中枢/关键点
2. **实战面板**：用持仓真实数据跑 `chan_analysis.py` 管线（merge_inclusion→find_fractals→find_bi→calc_macd），画价格线+MACD柱双轴，标注真实笔点位与面积数字

## 关键代码要点

- 中文字体：`plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei']`（fc-list 确认已装）；findfont weight warning 可忽略
- **merged K线只有 high/low/date/idx/close，没有 open 字段**——画不了蜡烛实体，用细竖线(high-low)或只画 close 线；先查 keys 再画
- 笔折线：bi 的 date 是合并K线日期，需写 x_of(date) 映射到子图索引；截取最近 N 根时注意 bi 点可能越界要过滤
- MACD柱颜色：红=正、绿=负；背驰面积按笔区间切片求和后直接标在注释里（真实数字最有说服力）
- 双轴：ax.bar 用左轴(MACD)，ax.twinx().plot 价格蓝线
- 写长绘图脚本用 write_file 到 /tmp/*.py 再 python3 运行——heredoc 内嵌脚本曾因 f-string/引号反复报错
- 自检：vision_analyze 检查布局（文字重叠/箭头指向），遇 provider 429 时确定性绘图可直接交付

## 中枢严格口径（用户纠正过）

ZD = max(三段各自低点), ZG = min(三段各自高点)。例：段1[1.605,1.851] ∩ 段2[1.753,1.851] ∩ 段3[1.753,2.029] = [1.753, 1.851]。离开段高点不属于中枢，勿框进矩形。算法输出的中枢可能更窄（相邻笔分组口径不同），教学与报告以手工三段口径为准，边界留缓冲。
