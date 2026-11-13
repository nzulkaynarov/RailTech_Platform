"""Обозначения номеров реестра (`/api/v1/numbering-labels`, eds.yaml, тег `registry`; задача «Н»)."""

from pydantic import BaseModel

from app.schemas.common import Strict
from app.services.numbering import NumberKind


class NumberLabelItem(BaseModel):
    kind: NumberKind
    label: str
    example: str


class NumberLabels(BaseModel):
    items: list[NumberLabelItem]


class NumberLabelsIn(Strict):
    labels: dict[str, str]
