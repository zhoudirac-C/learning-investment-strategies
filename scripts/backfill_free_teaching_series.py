"""一次性回填：卢本圆复盘「免费教学！！！」合集（season_id=4291413）9个历史视频。

翻动态feed找到对应视频动态 item，走标准 maybe_asr_video + save_dynamic_to_file 落盘。
不触碰 state 文件（历史动态不会再出现在feed首页，无需标记 processed）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.fetch_bilibili_up_v2 import (
    fetch_dynamic_list, classify_dynamic_type,
    maybe_asr_video, save_dynamic_to_file,
)
from scripts import bilibili_video_asr as asr_mod

UID = "550494308"
TARGET_BVIDS = {
    "BV1MySRYKESE", "BV1hdDUY4ENq", "BV161S2YaEqx", "BV1BsDKYmExC",
    "BV1vTUVYxEEX", "BV1f7m6YzEiY", "BV1odmmYoERG", "BV1QuKJzzEcw",
    "BV1Ju3f6hEWm",
}
MAX_PAGES = 80


def get_bvid(item: dict) -> str:
    return str(((item.get("modules", {}).get("module_dynamic") or {})
                .get("major", {}).get("archive", {}) or {}).get("bvid", ""))


def main() -> None:
    sessdata = os.environ.get("BILIBILI_SESSDATA", "")
    asr_cfg = asr_mod.load_config()

    # 1. 翻feed找目标动态
    found: dict[str, dict] = {}
    offset = ""
    for page in range(1, MAX_PAGES + 1):
        resp = fetch_dynamic_list(UID, sessdata, offset=offset)
        if resp.get("code") != 0:
            print(f"ERROR: page {page} api {resp.get('code')} {resp.get('message')}", file=sys.stderr)
            break
        data = resp.get("data", {})
        for item in data.get("items", []):
            if classify_dynamic_type(item) != "视频":
                continue
            bv = get_bvid(item)
            if bv in TARGET_BVIDS and bv not in found:
                found[bv] = item
                print(f"page {page}: hit {bv}", file=sys.stderr)
        if len(found) == len(TARGET_BVIDS):
            break
        if not data.get("has_more"):
            break
        offset = data.get("offset", "")
        time.sleep(1.2)

    missing = TARGET_BVIDS - set(found)
    if missing:
        print(f"WARN: feed中未找到 {len(missing)} 个: {sorted(missing)}", file=sys.stderr)

    # 2. 按发布时间正序逐个 ASR + 落盘
    def pub_ts(item: dict) -> int:
        return int((item.get("modules", {}).get("module_author") or {}).get("publish_ts", 0))

    items = sorted(found.items(), key=lambda kv: pub_ts(kv[1]))
    for i, (bv, item) in enumerate(items, 1):
        dyn_id = str(item.get("id_str", ""))
        print(f"[{i}/{len(items)}] ASR {bv} (dyn {dyn_id})...", file=sys.stderr)
        asr_text, asr_meta = maybe_asr_video(item, sessdata, asr_cfg, dyn_id)
        path = save_dynamic_to_file(
            item, UID, dyn_id,
            asr_text=asr_text, asr_meta=asr_meta,
        )
        ok = asr_text and not asr_text.startswith("[ASR")
        print(f"SAVED {'ASR_OK' if ok else 'ASR_FAIL'}: {path}")

    print("DONE")


if __name__ == "__main__":
    main()
