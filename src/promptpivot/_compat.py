"""Pydantic v1 / v2 compatibility. The rest of the package calls these helpers, never the
version-specific methods (``model_dump``/``dict``, ``model_validate``/``parse_obj``)."""

from __future__ import annotations

from typing import Any, TypeVar

import pydantic
from pydantic import BaseModel

PYDANTIC_V2 = pydantic.VERSION.startswith("2.")

M = TypeVar("M", bound=BaseModel)


def dump(model: BaseModel) -> dict[str, Any]:
    """The model as a plain dict."""
    if PYDANTIC_V2:
        return model.model_dump()
    return model.dict()  # pragma: no cover - pydantic v1


def validate(cls: type[M], data: Any) -> M:
    """Build and validate ``cls`` from ``data``."""
    if PYDANTIC_V2:
        return cls.model_validate(data)
    return cls.parse_obj(data)  # pragma: no cover - pydantic v1


def construct(cls: type[M]) -> M:
    """An instance of ``cls`` built from its defaults, without validation."""
    if PYDANTIC_V2:
        return cls.model_construct()
    return cls.construct()  # pragma: no cover - pydantic v1


if PYDANTIC_V2:
    from pydantic import ConfigDict

    class FrozenModel(BaseModel):
        """Immutable model that keeps unknown keys."""

        model_config = ConfigDict(frozen=True, extra="allow")

    class StrictFrozenModel(BaseModel):
        """Immutable model that ignores unknown keys."""

        model_config = ConfigDict(frozen=True)

else:  # pragma: no cover - pydantic v1

    class FrozenModel(BaseModel):  # type: ignore[no-redef]
        """Immutable model that keeps unknown keys."""

        class Config:
            frozen = True
            extra = "allow"

    class StrictFrozenModel(BaseModel):  # type: ignore[no-redef]
        """Immutable model that ignores unknown keys."""

        class Config:
            frozen = True
