from datetime import datetime

from pydantic import BaseModel, Field


class Organization(BaseModel):
    id: str = Field(description="UUID identifier")
    name: str
    slug: str
    created_at: datetime


class Project(BaseModel):
    id: str = Field(description="UUID identifier")
    org_id: str
    name: str
    slug: str
    created_at: datetime


class User(BaseModel):
    id: str = Field(description="UUID identifier")
    email: str
    subject: str | None = None
    name: str | None = None
    created_at: datetime


class Membership(BaseModel):
    id: str = Field(description="UUID identifier")
    org_id: str
    user_id: str
    role: str = Field(pattern="^(owner|admin|member|viewer)$")
    created_at: datetime


class Invitation(BaseModel):
    id: str = Field(description="UUID identifier")
    org_id: str
    email: str
    role: str = Field(default="member", pattern="^(owner|admin|member|viewer)$")
    token: str
    status: str = Field(pattern="^(pending|accepted|revoked)$")
    invited_by_user_id: str
    created_at: datetime
    accepted_at: datetime | None = None
    expires_at: datetime


class OrgMember(BaseModel):
    user_id: str
    email: str
    role: str
    joined_at: datetime


class ProjectIngestKey(BaseModel):
    id: str = Field(description="UUID identifier")
    project_id: str
    name: str
    key_prefix: str
    key_hash: str = ""
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class Exchange(BaseModel):
    id: str = Field(description="UUID4 hex identifier")
    run_id: str
    project_id: str | None = None
    parent_run_id: str | None = None
    origin: str | None = None
    created_at: datetime
    started_at: datetime
    ended_at: datetime
    latency_ms: int = Field(ge=0)
    method: str
    path: str
    query: str | None = None
    request_headers: dict[str, str]
    request_body_hash: str | None = None
    response_status: int
    response_headers: dict[str, str]
    model: str | None = None
    usage: dict | None = None
    provider: str | None = None
    response_body_hash: str | None = None


class RunSummary(BaseModel):
    run_id: str
    step_count: int = Field(ge=1)
    started_at: datetime
    ended_at: datetime
    total_latency_ms: int = Field(ge=0)
    models: list[str]
    final_status: int
    created_at: datetime
    parent_run_id: str | None = None


class RegressionTest(BaseModel):
    id: str = Field(description="UUID4 hex identifier")
    name: str
    baseline_run_id: str
    project_id: str | None = None
    created_at: datetime
    mode: str = Field(default="semantic", pattern="^(exact|semantic)$")


class StepDiff(BaseModel):
    step_index: int = Field(ge=1)
    request_match: bool
    response_match: bool
    diff_kind: str = Field(
        default="none",
        pattern="^(none|wording|tool_call|finish_reason|structure|request)$",
    )


class TestResult(BaseModel):
    id: str = Field(description="UUID4 hex identifier")
    test_id: str
    run_at: datetime
    status: str = Field(pattern="^(pass|fail)$")
    total_steps: int = Field(ge=0)
    matched_steps: int = Field(ge=0)
    first_divergent_step_index: int | None = Field(default=None, ge=1)
    detail: str
    candidate_run_id: str | None = None
    step_diffs: list[StepDiff] = Field(default_factory=list)
