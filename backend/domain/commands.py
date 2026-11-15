"""Validated application inputs, independent of HTTP and persistence adapters."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["article", "course", "document", "podcast", "webinar", "calculator"]
Category = Literal["business", "finance", "team", "marketing", "technology"]
Action = Literal["impression", "clicked", "viewed", "interested", "started", "completed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    username: str = Field(min_length=3, max_length=64, pattern="^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.casefold()


class Profile(StrictModel):
    categories: list[Category] = Field(default_factory=list, max_length=5)
    goal: str | None = Field(default=None, min_length=1, max_length=300)
    industry: str | None = Field(default=None, min_length=1, max_length=150)
    business_stage: str | None = Field(default=None, max_length=50)
    experience: str | None = Field(default=None, max_length=50)
    preferred_kinds: list[Kind] = Field(default_factory=list, max_length=6)
    region: str | None = Field(default=None, max_length=150)


class GenerationRequest(StrictModel):
    generation: str = Field(min_length=1, max_length=150)


class ActivityInput(GenerationRequest):
    event_id: str = Field(min_length=1, max_length=80)
    entity_key: str = Field(min_length=1, max_length=150)
    action: Action
    position: int | None = Field(default=None, ge=1, le=50)


class CatalogMaterial(StrictModel):
    entity_key: str = Field(min_length=1, max_length=150)
    kind: Kind
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=50000)
    topics: list[str] = Field(default_factory=list, max_length=100)
    published: bool = False
    access: Literal["public", "restricted"] = "restricted"
    canonical_url: str | None = Field(default=None, max_length=2000)
    price_amount: str | None = Field(default=None, max_length=40)
    price_currency: str | None = None

    @model_validator(mode="after")
    def validate_material(self) -> CatalogMaterial:
        if not self.entity_key.startswith(self.kind + ":"):
            raise ValueError("entity_key must start with kind:")
        if self.canonical_url:
            url = urlsplit(self.canonical_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("canonical_url must be an HTTPS URL without credentials")
        if (self.price_amount is None) != (self.price_currency is None):
            raise ValueError("Provide both price_amount and price_currency, or neither")
        if self.price_amount is not None:
            try:
                value = Decimal(self.price_amount)
            except InvalidOperation as error:
                raise ValueError("Invalid price") from error
            if not value.is_finite() or value < 0 or value > Decimal("999999999999.99"):
                raise ValueError("Invalid price")
            exponent = value.as_tuple().exponent
            if isinstance(exponent, int) and exponent < -2:
                raise ValueError("Price supports at most two decimal places")
            if not re.fullmatch("[A-Z]{3}", self.price_currency or ""):
                raise ValueError("Use a three-letter uppercase currency code")
        return self


class CatalogImport(GenerationRequest):
    materials: list[CatalogMaterial] = Field(max_length=100000)

    @model_validator(mode="after")
    def unique_keys(self) -> CatalogImport:
        keys = [item.entity_key for item in self.materials]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate entity_key")
        return self
