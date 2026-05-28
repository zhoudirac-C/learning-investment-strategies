# Original 原稿

这里保存从外部平台（B站、微博、公众号等）自动拉取的原稿，未经任何改写或结构化处理。

## 目录结构

```
sources/original/
├── bilibili/          # B站动态原稿
├── weibo/             # 微博原稿（预留）
├── wechat/            # 公众号原稿（预留）
└── README.md
```

## 文件命名

`sources/original/<platform>/YYYY-MM-DD-HHMM-<type>-<title_or_id>.md`

例如：
- `sources/original/bilibili/2026-05-28-0930-动态-1207282377456353288.md`
- `sources/original/bilibili/2026-05-28-1015-评论-早盘补充.md`

## 与原稿的关系

- `sources/original/`：机器拉取的原稿，保留原始格式（含HTML标签、B站表情等）
- `sources/raw/财经/`：人工整理后的结构化raw文档，用于qing-learning ingest
- `sources/incoming/`：待确认/待清洗的临时材料

## 处理流程

```
original（机器拉取原稿）
    ↓ 人工确认/清洗
raw（结构化整理）
    ↓ qing-learning ingest
claims / wiki / framework
```

## 注意

- original 文件不直接参与 qing-learning ingest
- 需要人工确认内容完整、格式可读后，再整理为 raw
- 图片/视频链接保留在原稿中，raw中用文字描述替代
