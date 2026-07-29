#!/usr/bin/env python3
"""
B站二维码登录脚本

用法:
    uv run python scripts/bilibili_qr_login.py
    uv run python scripts/bilibili_qr_login.py --output ~/.hermes/bilibili_sessdata.txt

流程:
    1. 生成二维码图片
    2. 发送二维码给用户扫描
    3. 轮询扫码状态
    4. 登录成功后保存 SESSDATA

输出:
    - 二维码图片路径 (stdout 打印 MEDIA:path)
    - SESSDATA 保存到指定文件
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import qrcode


# ── 配置 ──────────────────────────────────────────────────────────

QRCODE_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
POLL_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_OUTPUT = Path.home() / ".hermes" / "bilibili_sessdata.txt"


# ── API 调用 ──────────────────────────────────────────────────────

def api_request(url: str, data: dict | None = None) -> dict:
    """发送HTTP请求并返回JSON."""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://passport.bilibili.com",
    }
    if data:
        post_data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
    else:
        req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def generate_qrcode() -> tuple[str, str]:
    """生成二维码，返回 (qrcode_key, qrcode_url)."""
    result = api_request(QRCODE_API)
    if result.get("code") != 0:
        raise RuntimeError(f"生成二维码失败: {result}")
    data = result["data"]
    return data["qrcode_key"], data["url"]


def poll_login_status(qrcode_key: str) -> dict:
    """轮询扫码状态."""
    url = f"{POLL_API}?qrcode_key={qrcode_key}"
    return api_request(url)


# ── 二维码图片生成 ────────────────────────────────────────────────

def create_qr_image(url: str, output_path: Path) -> Path:
    """生成二维码图片并保存."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_path)
    return output_path


# ── Cookie 解析 ───────────────────────────────────────────────────

def extract_sessdata(cookies: list[dict]) -> str | None:
    """从cookie列表中提取SESSDATA."""
    for cookie in cookies:
        if cookie.get("name") == "SESSDATA":
            return cookie.get("value")
    return None


def extract_dedeuserid(cookies: list[dict]) -> str | None:
    """从cookie列表中提取DedeUserID."""
    for cookie in cookies:
        if cookie.get("name") == "DedeUserID":
            return cookie.get("value")
    return None


# ── 主流程 ────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="B站二维码登录")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"SESSDATA输出文件路径 (默认: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="扫码超时时间(秒) (默认: 180)",
    )
    args = parser.parse_args()

    # 确保输出目录存在
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # 1. 生成二维码
    print("正在生成二维码...", file=sys.stderr)
    qrcode_key, qrcode_url = generate_qrcode()

    # 2. 保存二维码图片
    qr_path = args.output.parent / "bilibili_qrcode.png"
    create_qr_image(qrcode_url, qr_path)
    print(f"MEDIA:{qr_path}")
    print(f"请使用B站APP扫描上方二维码", file=sys.stderr)

    # 3. 轮询扫码状态
    start_time = time.time()
    while time.time() - start_time < args.timeout:
        result = poll_login_status(qrcode_key)
        code = result.get("code", -1)
        data = result.get("data", {})
        status = data.get("code", -1)

        # status: 0=成功, 86038=已失效, 86090=已扫码未确认, 86101=未扫码
        if status == 0:
            # 登录成功
            cookies = data.get("cookie_info", {}).get("cookies", [])
            sessdata = extract_sessdata(cookies)
            dedeuserid = extract_dedeuserid(cookies)

            # 新API: SESSDATA 可能在 URL 参数中（cookie_info 为空时）
            if not sessdata:
                login_url = data.get("url", "")
                if login_url and "SESSDATA=" in login_url:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(login_url)
                    params = urllib.parse.parse_qs(parsed.query)
                    sessdata = params.get("SESSDATA", [None])[0]

            if not sessdata:
                print("ERROR: 登录成功但未获取到SESSDATA", file=sys.stderr)
                return 1

            # 保存SESSDATA
            args.output.write_text(sessdata, encoding="utf-8")
            print(f"\n登录成功! 用户ID: {dedeuserid}", file=sys.stderr)
            print(f"SESSDATA已保存到: {args.output}", file=sys.stderr)
            print(f"SESSDATA: {sessdata[:20]}...", file=sys.stderr)

            # 清理二维码图片
            qr_path.unlink(missing_ok=True)
            return 0

        elif status == 86038:
            print("ERROR: 二维码已失效，请重新运行脚本", file=sys.stderr)
            qr_path.unlink(missing_ok=True)
            return 1

        elif status == 86090:
            print("已扫码，请在手机上确认登录...", file=sys.stderr)

        elif status == 86101:
            # 未扫码，静默等待
            pass

        time.sleep(2)

    print("ERROR: 扫码超时，请重新运行脚本", file=sys.stderr)
    qr_path.unlink(missing_ok=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
