#!/usr/bin/env python3
"""
B站 QR 登录自动刷新脚本 — 二维码过期后自动重新生成，无需手动重启。

用法:
    python3 qr_login_auto.py

输出:
    - stdout: MEDIA:path (二维码图片路径，Hermes 自动发送给用户)
    - stderr: 进度日志
    - 登录成功后自动保存 SESSDATA 到 ~/.hermes/bilibili_sessdata.txt

行为:
    1. 生成二维码，输出 MEDIA:path
    2. 轮询扫码状态（每 2s）
    3. 检测到"已扫码，请确认"时打印提示
    4. 二维码过期（86038）自动重新生成
    5. 登录成功（status=0）自动提取并保存 SESSDATA（支持新旧两种API格式）
    6. 登录成功但 SESSDATA 提取失败时，打印完整 API 响应用于调试
"""
import json
import time
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

import qrcode as qr

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
OUTPUT = Path.home() / ".hermes" / "bilibili_sessdata.txt"
QR_PATH = Path.home() / ".hermes" / "bilibili_qrcode.png"
POLL_INTERVAL = 2
QR_TIMEOUT = 180


def api_get(url: str) -> dict:
    """通用 B站 API GET 请求"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": "https://passport.bilibili.com"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def generate_qr() -> tuple[str, str]:
    """生成二维码，返回 (qrcode_key, qrcode_url)"""
    data = api_get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
    if data.get("code") != 0:
        raise RuntimeError(f"QR 生成失败: {data}")

    qrcode_key = data["data"]["qrcode_key"]
    qrcode_url = data["data"]["url"]

    img = qr.make(qrcode_url)
    img.save(QR_PATH)

    return qrcode_key, qrcode_url


def poll_login(qrcode_key: str) -> tuple[int, dict]:
    """轮询扫码状态，返回 (data.code, 完整API响应)"""
    data = api_get(
        f"https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}"
    )
    return data.get("data", {}).get("code", -1), data


def extract_sessdata_from_url(url_str: str) -> str | None:
    """从 B站 API 返回的 redirect URL 中提取 SESSDATA 参数
    (2026年7月API变更后格式: SESSDATA 在 data.url 的 query 参数中)
    """
    parsed = urllib.parse.urlparse(url_str)
    params = urllib.parse.parse_qs(parsed.query)
    return params.get("SESSDATA", [None])[0]


def extract_and_save_sessdata(api_response: dict) -> bool:
    """从登录成功响应中提取 SESSDATA 并保存，返回是否成功

    支持两种API格式:
    1. 旧格式: data.cookie_info.cookies[] -> name=SESSDATA, value=...
    2. 新格式(2026年7月): data.url 中提取 SESSDATA 参数
    """
    sessdata = None

    # 方案1: 从 cookie_info.cookies 提取（旧格式）
    cookies = (
        api_response.get("data", {})
        .get("cookie_info", {})
        .get("cookies", [])
    )
    for c in cookies:
        if c.get("name") == "SESSDATA":
            sessdata = c.get("value")
            break

    # 方案2: 从 data.url 提取（2026年7月后的新格式）
    if not sessdata:
        url = api_response.get("data", {}).get("url", "")
        if url:
            sessdata = extract_sessdata_from_url(url)

    if not sessdata:
        print("无法从两种格式中提取SESSDATA! 打印完整响应:", file=sys.stderr)
        print(json.dumps(api_response, ensure_ascii=False, indent=2), file=sys.stderr)
        return False

    OUTPUT.write_text(sessdata)

    # 验证新 SESSDATA
    req = urllib.request.Request(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={"User-Agent": USER_AGENT, "Cookie": f"SESSDATA={sessdata}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        nav = json.loads(resp.read())
    uname = nav.get("data", {}).get("uname", "?")
    print(f"登录成功! 用户: {uname}  SESSDATA已保存({len(sessdata)} chars)", file=sys.stderr)
    return True


def main():
    print("B站 QR 登录 — 自动刷新模式启动", file=sys.stderr)

    while True:
        try:
            qrcode_key, _ = generate_qr()
            print(f"MEDIA:{QR_PATH}")
            print("新二维码已生成，请扫码并在 APP 上确认登录", file=sys.stderr)

            start = time.time()
            expired = False

            while time.time() - start < QR_TIMEOUT:
                status, api_resp = poll_login(qrcode_key)

                if status == 0:
                    # 登录成功
                    if extract_and_save_sessdata(api_resp):
                        sys.exit(0)
                    else:
                        print("SESSDATA提取失败，5秒后重试...", file=sys.stderr)
                        time.sleep(5)

                elif status == 86038:
                    print("二维码已失效，自动刷新...", file=sys.stderr)
                    expired = True
                    break

                elif status == 86090:
                    print("已扫码，请点确认...", file=sys.stderr)

                # status == 86101: 未扫码，静默
                time.sleep(POLL_INTERVAL)

            if not expired:
                print(f"超时({QR_TIMEOUT}s)，自动刷新二维码...", file=sys.stderr)

        except urllib.error.URLError as e:
            print(f"网络异常({e.reason})，5秒后重试...", file=sys.stderr)
            time.sleep(5)
        except Exception as e:
            print(f"异常: {e}，5秒后重试...", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
