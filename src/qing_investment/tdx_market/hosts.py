"""通达信行情服务器目录与能力分类。

本模块移植自 gotdx 的 DefaultHostCatalog，把服务器按「能力」分类，
使得上层客户端可以按请求类型（实时行情/K线/分时/财务/板块/港股）路由到
真正支持该能力的服务器池，再按 Weight 加权负载均衡 + 失败故障转移。

能力分类说明（对应 gotdx 的 mainCapabilities / metadataCapabilities /
exCapabilities / macCapabilities / macMetadataCapabilities）：

- mainCapabilities:    A股行情 + K线 + 列表 + 分时 + 分笔 + 财务 + 除权除息 + 板块
- metadataCapabilities: 仅列表/分时/财务/除权除息/板块/文件（不支持实时行情/K线/分笔）
- exCapabilities:      港股行情 + 港股K线（Ex 协议，port 7727）
- macCapabilities:     MAC板块 + MAC行情
- macMetadataCapabilities: MAC板块/行情 + 标准协议元数据能力

注意：HqHosts 仅用于遗留兼容，新代码请使用 DefaultHostCatalog /
HostsForCapability。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Flag, auto


# =============================================================================
# Capability 定义
# =============================================================================

class HostCapability(Flag):
    """服务器能力位标志。"""

    NONE = 0
    CapMainQuote = auto()    # A股实时行情（SH/SZ/BJ）
    CapMainKline = auto()    # A股K线（含指数）
    CapMainList = auto()     # 证券列表
    CapMainMinute = auto()   # 分时图
    CapMainTrade = auto()    # 分笔成交
    CapMainFinance = auto()  # 财务数据
    CapMainXdxr = auto()     # 除权除息
    CapMainFile = auto()     # 文件数据
    CapSector880 = auto()    # 板块数据（880 板块）
    CapExQuote = auto()      # 港股行情（Ex 协议）
    CapExKline = auto()      # 港股K线（Ex 协议）
    CapMacBoard = auto()     # MAC 板块
    CapMacQuote = auto()     # MAC 行情


# 能力集合（对应 gotdx 的各类 capabilities 列表）
mainCapabilities = (
    HostCapability.CapMainQuote
    | HostCapability.CapMainKline
    | HostCapability.CapMainList
    | HostCapability.CapMainMinute
    | HostCapability.CapMainTrade
    | HostCapability.CapMainFinance
    | HostCapability.CapMainXdxr
    | HostCapability.CapMainFile
    | HostCapability.CapSector880
)

brokerCapabilities = mainCapabilities

# 仅元数据：支持列表/分时/财务/除权除息/板块与 block 文件，
# 但不支持实时行情/K线/分笔，不能进入 quote/kline/trade 路由
metadataCapabilities = (
    HostCapability.CapMainList
    | HostCapability.CapMainMinute
    | HostCapability.CapMainFinance
    | HostCapability.CapMainXdxr
    | HostCapability.CapMainFile
    | HostCapability.CapSector880
)

# 港股行情 + 港股K线（Ex 协议）
exCapabilities = HostCapability.CapExQuote | HostCapability.CapExKline

# MAC 板块 + MAC 行情
macCapabilities = HostCapability.CapMacBoard | HostCapability.CapMacQuote

# MAC 板块/行情 + 标准协议元数据能力
macMetadataCapabilities = (
    HostCapability.CapMainList
    | HostCapability.CapMainMinute
    | HostCapability.CapMainFinance
    | HostCapability.CapMainXdxr
    | HostCapability.CapMainFile
    | HostCapability.CapSector880
    | HostCapability.CapMacBoard
    | HostCapability.CapMacQuote
)


# =============================================================================
# HostClass 与 HostInfo
# =============================================================================

HostClassMain = "main"
HostClassBroker = "broker"
HostClassEx = "ex"
HostClassMAC = "mac"
HostClassMACEx = "mac_ex"


@dataclass(frozen=True)
class HostInfo:
    """一台行情服务器的描述。"""

    ID: str
    Name: str
    IP: str
    Port: int
    Class: str
    Capabilities: HostCapability
    Region: str = "cloud"
    Weight: int = 60
    Enabled: bool = True


# =============================================================================
# DefaultHostCatalog — 能力感知的服务器注册表
# =============================================================================

DefaultHostCatalog: list[HostInfo] = [
    # =========================================================================
    # 全能主服务器（A股 + 指数 + 北交所）
    # =========================================================================
    HostInfo("main-huawei-1", "华为云1", "124.70.199.56", 7709, HostClassMain, metadataCapabilities, "cloud", 60),
    HostInfo("main-tencent-3", "腾讯云1", "175.178.112.197", 7709, HostClassMain, mainCapabilities, "cloud", 105),
    HostInfo("main-huawei-2", "华为云2", "116.205.163.254", 7709, HostClassMain, metadataCapabilities, "cloud", 60),
    HostInfo("main-huawei-3", "华为云3", "116.205.183.150", 7709, HostClassMain, metadataCapabilities, "cloud", 60),
    HostInfo("main-huawei-4", "华为云4", "116.205.171.132", 7709, HostClassMain, metadataCapabilities, "cloud", 60),
    HostInfo("main-tencent-5", "腾讯云3", "111.229.247.189", 7709, HostClassMain, metadataCapabilities, "cloud", 60),
    HostInfo("main-huawei-5", "华为云5", "121.36.225.169", 7709, HostClassMain, metadataCapabilities, "cloud", 60),
    HostInfo("main-huawei-6", "华为云6", "123.60.70.228", 7709, HostClassMain, metadataCapabilities, "cloud", 60),

    # 电信/联通服务器（全能，同一 IP 池子）
    HostInfo("main-gd-telecom", "广东电信", "183.60.224.178", 7709, HostClassMain, mainCapabilities, "gd", 100),
    HostInfo("main-hz-telecom", "杭州电信", "218.75.126.9", 7709, HostClassMain, mainCapabilities, "zj", 100),
    HostInfo("main-hz-telecom-2", "杭州电信2", "115.238.90.165", 7709, HostClassMain, mainCapabilities, "zj", 100),
    HostInfo("main-hz-telecom-4", "杭州电信4", "60.12.136.250", 7709, HostClassMain, mainCapabilities, "zj", 100),
    HostInfo("main-zj-telecom", "浙江电信", "60.191.117.167", 7709, HostClassMain, mainCapabilities, "zj", 95),
    HostInfo("main-zj-telecom-2", "浙江电信2", "115.238.56.198", 7709, HostClassMain, mainCapabilities, "zj", 95),
    HostInfo("main-sh-telecom", "上海电信", "180.153.18.170", 7709, HostClassMain, mainCapabilities, "sh", 95),
    HostInfo("main-cd-telecom", "上证云成都电信", "218.6.170.47", 7709, HostClassMain, mainCapabilities, "cd", 95),
    HostInfo("main-bj-telecom", "上证云北京联通", "123.125.108.14", 7709, HostClassMain, mainCapabilities, "bj", 95),
    HostInfo("main-huawei-telecom", "通达信华为云", "124.71.187.122", 7709, HostClassMain, mainCapabilities, "cloud", 95),
    # Z80 端口（HTTP 协议，部分服务器使用）
    HostInfo("main-sh-telecom-z80", "上海电信Z80", "180.153.18.172", 80, HostClassMain, mainCapabilities, "sh", 90),
    HostInfo("main-bj-unicom-z80", "北京联通Z80", "202.108.253.139", 80, HostClassMain, mainCapabilities, "bj", 90),

    # 不可用的电信服务器（当前网络连不上，保留配置以备其他网络环境）
    HostInfo("main-sh-telecom-2", "上海电信2", "180.153.18.171", 7709, HostClassMain, mainCapabilities, "sh", 95, False),
    HostInfo("main-bj-unicom", "北京联通", "202.108.253.130", 7709, HostClassMain, mainCapabilities, "bj", 95, False),
    HostInfo("main-bj-unicom-2", "北京联通2", "202.108.253.131", 7709, HostClassMain, mainCapabilities, "bj", 95, False),
    HostInfo("main-hz-telecom-5", "杭州电信5", "218.108.98.244", 7709, HostClassMain, mainCapabilities, "zj", 95, False),
    HostInfo("main-hz-telecom-6", "杭州电信6", "218.108.47.69", 7709, HostClassMain, mainCapabilities, "zj", 95, False),
    HostInfo("main-wh-telecom", "武汉电信", "59.175.238.38", 7709, HostClassMain, mainCapabilities, "wh", 95, False),
    HostInfo("main-cgr-telecom-1", "长城国瑞电信1", "218.85.139.19", 7709, HostClassMain, mainCapabilities, "fj", 95, False),
    HostInfo("main-cgr-telecom-2", "长城国瑞电信2", "218.85.139.20", 7709, HostClassMain, mainCapabilities, "fj", 95, False),
    HostInfo("main-cgr-unicom", "长城国瑞网通", "58.23.131.163", 7709, HostClassMain, mainCapabilities, "fj", 95, False),

    # 元数据服务器（标准协议，不支持实时行情/K线/分笔）
    HostInfo("main-tencent-1", "通达信云1", "110.41.147.114", 7709, HostClassMain, metadataCapabilities, "cloud", 55),
    HostInfo("main-tencent-2", "通达信云2", "110.41.2.72", 7709, HostClassMain, metadataCapabilities, "cloud", 55),
    HostInfo("main-tencent-4", "腾讯云2", "101.33.225.16", 7709, HostClassMain, metadataCapabilities, "cloud", 55),
    HostInfo("main-tencent-6", "腾讯云4", "122.51.120.217", 7709, HostClassMain, metadataCapabilities, "cloud", 55),

    # MAC 服务器（板块数据，MAC 协议）
    HostInfo("mac-huawei-1", "MAC主站1", "121.36.248.138", 7709, HostClassMAC, macMetadataCapabilities, "cloud", 75),
    HostInfo("mac-huawei-2", "MAC主站2", "123.60.47.136", 7709, HostClassMAC, macMetadataCapabilities, "cloud", 75),

    # 港股服务器（Ex 协议，port 7727）
    HostInfo("ex-aliyun-1", "扩展行情1", "112.74.214.43", 7727, HostClassEx, exCapabilities, "aliyun", 90),
    HostInfo("ex-aliyun-2", "扩展行情2", "120.25.218.6", 7727, HostClassEx, exCapabilities, "aliyun", 90),
    HostInfo("ex-huawei-1", "扩展行情3", "116.205.143.214", 7727, HostClassEx, exCapabilities, "cloud", 90),

    # MAC 扩展服务器（Ex 协议 + MAC）
    HostInfo("mac-ex-huawei-1", "MAC扩展1", "116.205.135.205", 7727, HostClassMACEx, exCapabilities, "cloud", 80),
    HostInfo("mac-ex-huawei-2", "MAC扩展2", "121.37.232.167", 7727, HostClassMACEx, exCapabilities, "cloud", 80),
]


# 遗留兼容列表（仅保留实际可用服务器，供旧代码引用）
HqHosts = [
    {"name": h.Name, "ip": h.IP, "port": h.Port}
    for h in DefaultHostCatalog
    if h.Enabled
]


def HostsForClass(class_: str) -> list[HostInfo]:
    """返回某 class 下所有 enabled 的服务器。"""
    return [h for h in DefaultHostCatalog if h.Enabled and h.Class == class_]


def HostsForCapability(cap: HostCapability) -> list[HostInfo]:
    """返回支持指定能力的所有 enabled 服务器。

    能力按位包含判断：服务器 Capabilities 必须包含请求的 cap 位。
    """
    return [h for h in DefaultHostCatalog if h.Enabled and (h.Capabilities & cap)]


def weighted_choice(hosts: list[HostInfo], rng: random.Random | None = None) -> HostInfo | None:
    """按 Weight 加权随机选择一台服务器。"""
    if not hosts:
        return None
    rng = rng or random
    total = sum(h.Weight for h in hosts)
    if total <= 0:
        return rng.choice(hosts)
    r = rng.uniform(0, total)
    upto = 0
    for h in hosts:
        upto += h.Weight
        if upto >= r:
            return h
    return hosts[-1]
