import pytest

from app.domain.scoring import ScoreInputs, compute_score


def inputs(**overrides: object) -> ScoreInputs:
    base: dict[str, object] = {
        "has_need": False,
        "has_product": False,
        "timeline": None,
        "decision_role": None,
        "asked_price": False,
        "requested_contact": False,
        "negative": False,
    }
    base.update(overrides)
    return ScoreInputs(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, 0),
        ({"has_need": True}, 25),
        ({"has_product": True}, 15),
        ({"timeline": "<1m"}, 20),
        ({"timeline": "<3m"}, 20),
        ({"timeline": "<12m"}, 10),
        ({"timeline": ">12m"}, 0),
        ({"decision_role": "decision_maker"}, 20),
        ({"decision_role": "influencer"}, 10),
        ({"decision_role": "researcher"}, 0),
        ({"asked_price": True}, 15),
        ({"requested_contact": True}, 25),
        ({"negative": True}, 0),
        ({"has_need": True, "negative": True}, 15),
        (
            {
                "has_need": True,
                "has_product": True,
                "timeline": "<3m",
                "decision_role": "decision_maker",
            },
            80,
        ),
        (
            {
                "has_need": True,
                "has_product": True,
                "timeline": "<1m",
                "decision_role": "decision_maker",
                "asked_price": True,
                "requested_contact": True,
            },
            100,
        ),
    ],
)
def test_compute_score(overrides: dict[str, object], expected: int) -> None:
    assert compute_score(inputs(**overrides)) == expected
