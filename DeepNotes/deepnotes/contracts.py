"""Bounded data contracts shared by HTTP handlers and model pipelines."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EntryIn(Contract):
    # Code indentation and original surrounding whitespace are source data.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    content: str = Field(min_length=1, max_length=20000)
    source_url: str = Field(default="", max_length=2000)
    source_title: str = Field(default="", max_length=500)

    @field_validator("content")
    @classmethod
    def nonblank_content(cls, value):
        if not value.strip():
            raise ValueError("Enter a nonblank note")
        return value

    @field_validator("source_url")
    @classmethod
    def safe_url(cls, value):
        value = value.strip()
        if value and not value.lower().startswith(("https://", "http://")):
            raise ValueError("Source URL must use http or https")
        return value


class GuidanceIn(Contract):
    scope: Literal["entry", "class", "global"]
    target_id: str | None = Field(default=None, max_length=80)
    content: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def target(self):
        if self.scope != "global" and not self.target_id:
            raise ValueError("Entry/class guidance needs a target ID")
        if self.scope == "global" and self.target_id:
            raise ValueError("Global guidance must not have a target")
        return self


class QueryIn(Contract):
    question: str = Field(min_length=1, max_length=4000)


class RollbackIn(Contract):
    version_id: int = Field(gt=0)


class CatalogClass(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1200)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    parent_id: str | None = None
    routing_hints: str = Field(default="", max_length=1000)

    @field_validator("aliases")
    @classmethod
    def bounded_aliases(cls, value):
        if any(not item or len(item) > 100 for item in value):
            raise ValueError("Aliases must have 1–100 characters")
        return value


class Evidence(Contract):
    entry_id: int = Field(gt=0)
    excerpt: str = Field(min_length=1, max_length=1000)


class Relation(Contract):
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    relation: Literal["related_to", "part_of", "supports", "contradicts", "prerequisite_for"]
    evidence: list[Evidence] = Field(min_length=1, max_length=4)
    inferred: bool = True


class Interpretation(Contract):
    summary: str = Field(min_length=1, max_length=2000)
    intent: str = Field(min_length=1, max_length=100)
    class_ids: list[str] = Field(min_length=1, max_length=5)
    concepts: list[str] = Field(default_factory=list, max_length=20)
    relations: list[Relation] = Field(default_factory=list, max_length=20)
    rationale: str = Field(default="", max_length=1000)
    clarification: str = Field(default="", max_length=500)

    @field_validator("concepts")
    @classmethod
    def concepts_bounded(cls, value):
        if any(not item or len(item) > 120 for item in value):
            raise ValueError("Concepts must have 1–120 characters")
        return list(dict.fromkeys(value))


class StructureProposal(Contract):
    upserts: list[CatalogClass] = Field(default_factory=list, max_length=32)
    remove_ids: list[str] = Field(default_factory=list, max_length=32)
    rationale: str = Field(min_length=1, max_length=2000)
    support_entry_ids: list[int] = Field(default_factory=list, max_length=40)
    support_guidance_ids: list[int] = Field(default_factory=list, max_length=20)


class SearchPlan(Contract):
    terms: list[str] = Field(default_factory=list, max_length=12)
    class_ids: list[str] = Field(default_factory=list, max_length=8)
    intent: str = Field(default="", max_length=200)

    @field_validator("terms")
    @classmethod
    def bounded_terms(cls, value):
        if any(not item or len(item) > 100 for item in value):
            raise ValueError("Search terms must have 1–100 characters")
        return value


class Answer(Contract):
    answer: str = Field(min_length=1, max_length=16000)
    coverage: Literal["none", "partial", "sufficient"]
    general_knowledge: bool
    explanation: str = Field(min_length=1, max_length=2000)
    cited_entry_ids: list[int] = Field(default_factory=list, max_length=12)
