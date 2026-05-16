from qing_investment.paths import repo_root, resolve_repo_path


def test_repo_root_points_to_project_root():
    root = repo_root()
    assert (root / "pyproject.toml").exists()
    assert root.name == "learning-investment-strategies"


def test_resolve_repo_path_joins_parts():
    expected = repo_root() / "knowledge" / "claims"
    assert resolve_repo_path("knowledge", "claims") == expected
