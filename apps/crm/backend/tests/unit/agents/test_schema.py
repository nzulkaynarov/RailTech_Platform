from pydantic import BaseModel, Field

from app.agents.schema import strict_schema
from app.domain.qualification import QualifierOutput


class Inner(BaseModel):
    title: str = "x"
    note: str | None = None


class Outer(BaseModel):
    title: str = Field(default="t", max_length=10)
    score: float = Field(ge=0, le=1)
    inner: Inner


def test_all_properties_required_and_constraints_dropped() -> None:
    schema = strict_schema(Outer)
    assert schema["required"] == ["title", "score", "inner"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["score"] == {"type": "number"}
    assert schema["properties"]["title"] == {"type": "string"}
    inner = schema["$defs"]["Inner"]
    assert inner["required"] == ["title", "note"]
    assert "title" in inner["properties"]


def test_qualifier_output_schema_is_strict() -> None:
    schema = strict_schema(QualifierOutput)
    assert set(schema["required"]) == set(QualifierOutput.model_fields)
    assert "default" not in str(schema)
