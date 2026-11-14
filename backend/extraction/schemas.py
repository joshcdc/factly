"""What the LLM returns per source. Ids are assigned in code, never by the model."""

from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["person", "company", "location", "event", "concept"]


class ExtractedEntity(BaseModel):
    name: str = Field(description="A noun: the proper name of one specific thing, 1-4 words")
    type: EntityType
    description: str = Field(description="One short sentence, from the source only")


class ExtractedRelation(BaseModel):
    subject: str = Field(description="Entity name exactly as in `entities`")
    relationship: str = Field(description="Short verb phrase, e.g. 'invested in', 'founded'")
    object: str = Field(description="Entity name exactly as in `entities`")
    description: str = ""


class ExtractedExcerpt(BaseModel):
    quote: str = Field(description="Copied character-for-character from the source; one contiguous passage")
    reasoning: str = Field(description="Why this passage is relevant to the claim")


class SourceExtraction(BaseModel):
    entities: list[ExtractedEntity] = Field(description="At most 10, most relevant to the claim and its subject")
    relationships: list[ExtractedRelation] = Field(
        description="At most 12 facts the source states; subject and object must both be listed in `entities`")
    excerpts: list[ExtractedExcerpt] = Field(description="At most 3 passages most relevant to the claim")
