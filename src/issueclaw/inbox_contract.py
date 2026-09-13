"""Validated wire contract shared by replay transport and integration fixtures."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Issue", "Project", "Initiative", "Document"]
    action: Literal["create", "update", "remove"]
    data: dict[str, str]
    createdAt: str


class WorkItem(BaseModel):
    key: str
    generation: int = Field(gt=0)
    payload: Payload

    @model_validator(mode="after")
    def matching_identity(self):
        entity_id = self.payload.data.get("id")
        parts = self.key.split("/")
        if (
            not entity_id
            or len(parts) != 3
            or not parts[0]
            or parts[1:] != [self.payload.type, entity_id]
        ):
            raise ValueError("Work key does not match payload identity")
        return self


class Batch(BaseModel):
    stream: str = Field(min_length=1)
    token: str = Field(min_length=1)
    items: list[WorkItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_keys(self):
        if len({item.key for item in self.items}) != len(self.items):
            raise ValueError("Repeated work keys")
        return self


class Outcome(BaseModel):
    key: str
    success: bool
    deferred: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def exclusive_outcome(self):
        if self.success and self.deferred:
            raise ValueError("Published work cannot also be deferred")
        return self
