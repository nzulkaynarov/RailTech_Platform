import pytest

from app.cli.load_test import percentile, summarize


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [([], 95, 0.0), ([1.0], 95, 1.0), ([float(i) for i in range(1, 101)], 95, 95.0)],
)
def test_percentile_nearest_rank(values: list[float], q: float, expected: float) -> None:
    assert percentile(values, q) == expected


@pytest.mark.parametrize(
    ("latencies", "errors", "queue", "passed"),
    [
        ([1.0] * 100, 0, (3, 3), True),
        ([1.0] * 94 + [7.0] * 6, 0, (3, 3), False),  # p95 > 6 с
        ([1.0] * 100, 1, (3, 3), False),  # ошибка хода
        ([1.0] * 100, 0, (3, 9), False),  # очередь выросла
        ([1.0] * 100, 0, (3, 8), True),  # в пределах допуска
    ],
)
def test_summarize_gate(
    latencies: list[float], errors: int, queue: tuple[int, int], passed: bool
) -> None:
    assert summarize(50, latencies, errors, *queue).passed is passed
