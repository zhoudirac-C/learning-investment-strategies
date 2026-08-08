"""包骨架冒烟测试。"""


def test_package_importable():
    import investment_engine  # noqa: F401
    import investment_engine.industry_chain  # noqa: F401
    import investment_engine.distill  # noqa: F401
    import investment_engine.backtest  # noqa: F401


def test_qing_investment_still_importable():
    """红线：不修改 qing_investment，其导入必须保持正常。"""
    import qing_investment  # noqa: F401
    from qing_investment.monitor.rules import BuySignalRuleEngine  # noqa: F401
