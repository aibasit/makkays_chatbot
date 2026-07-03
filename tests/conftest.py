import pytest

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-stress",
        action="store_true",
        default=False,
        help="run slow/heavy stress tests",
    )

def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-stress"):
        # --run-stress given in cli: run stress tests
        return
    skip_stress = pytest.mark.skip(reason="need --run-stress option to run")
    for item in items:
        if "stress" in item.keywords:
            item.add_marker(skip_stress)
