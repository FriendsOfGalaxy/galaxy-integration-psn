from psn.library_utils import (
    alias_context_by_siblings,
    build_concept_siblings,
)


def test_build_concept_siblings():
    played = [
        {
            "titleId": "CUSA37191_00",
            "concept": {"id": 123, "titleIds": ["CUSA37191_00", "PPSA10609_00"]},
        }
    ]
    siblings = build_concept_siblings(played)
    assert siblings["CUSA37191_00"] == ["PPSA10609_00"]
    assert siblings["PPSA10609_00"] == ["CUSA37191_00"]


def test_alias_context_by_siblings():
    context = {"PPSA01325_00": ["trophy-a"]}
    siblings = {"PPSA99999_00": ["PPSA01325_00"]}
    alias_context_by_siblings(context, ["PPSA99999_00"], siblings)
    assert context["PPSA99999_00"] == ["trophy-a"]
