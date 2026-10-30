from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=10, max_length=255)


class UserSummary(BaseModel):
    id: int
    username: str
    display_name: str
    status: str
    roles: list[str] = Field(default_factory=list)


class PermissionSummary(BaseModel):
    code: str
    resource: str
    action: str
    description: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserSummary


class MeResponse(UserSummary):
    permissions: list[str] = Field(default_factory=list)
    readable_datasets: list[str] = Field(default_factory=list)
    writable_datasets: list[str] = Field(default_factory=list)
    allowed_regions: list[str] = Field(default_factory=list)
    dataset_regions: dict[str, list[str]] = Field(default_factory=dict)


class ConfirmationRequest(BaseModel):
    confirmation_type: Literal["document_delete", "vector_rebuild", "data_overwrite", "expansion_publish"]
    resource_type: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=128)
    decision: Literal["APPROVE", "REJECT"]
    comment: str = Field(min_length=1, max_length=2000)


class ConfirmationResponse(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    confirmation_type: str
    resource_type: str
    resource_id: str
    actor_user_id: int
    trace_id: str
