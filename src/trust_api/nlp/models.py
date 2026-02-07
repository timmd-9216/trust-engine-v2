"""Pydantic models for NLP corpus and candidate analysis."""

from typing import Any

from pydantic import BaseModel, Field


class EntityMention(BaseModel):
    """Single named entity with type and mention count."""

    text: str = Field(..., description="Entity surface form (e.g. candidate name)")
    type: str = Field(..., description="NER type: PER, ORG, LOC, etc.")
    count: int = Field(..., ge=0, description="Number of mentions in the corpus")


class AdjectivesByEntity(BaseModel):
    """Adjectives associated with a given entity (e.g. candidate)."""

    entity: str = Field(..., description="Entity/candidate identifier or name")
    adjectives: list[str] = Field(default_factory=list, description="List of adjectives")
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Adjective -> count in context of this entity",
    )


class TopNegativeAccount(BaseModel):
    """Account ranked by negative/disinformation-related activity."""

    account_id: str = Field(..., description="User id or screen name")
    score: float = Field(
        ..., description="Negativity / disinformation score (higher = more negative)"
    )
    post_count: int = Field(..., ge=0, description="Number of posts analyzed")
    extra: dict[str, Any] = Field(default_factory=dict, description="Optional metadata")


class AccountCluster(BaseModel):
    """Cluster of accounts that operate in a related way."""

    accounts: list[str] = Field(..., description="Account ids/screen names in this cluster")
    size: int = Field(..., ge=0, description="Number of accounts")
    extra: dict[str, Any] = Field(default_factory=dict, description="Optional cluster metadata")


class WordClusterByCandidate(BaseModel):
    """Cluster of words/adjectives associated with a candidate."""

    candidate_id: str = Field(..., description="Candidate identifier")
    words: list[str] = Field(default_factory=list, description="Representative words")
    adjectives: list[str] = Field(default_factory=list, description="Adjectives associated")
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Word/adjective -> count",
    )


class CorpusAnalyzeRequest(BaseModel):
    """Request body for corpus analysis: posts + optional candidate names."""

    posts: list[dict[str, Any]] = Field(
        ...,
        description="List of post objects with at least text (full_text/text/body), "
        "optional author (user_screen_name/author), optional candidate_id",
    )
    candidate_entities: list[str] | None = Field(
        default=None,
        description="Optional list of candidate/entity names for adjective association",
    )
    top_negative_k: int = Field(
        default=50,
        ge=1,
        le=500,
        description=(
            "Cantidad máxima de cuentas a devolver en top_negative_accounts. "
            "Las cuentas se ordenan por score de negatividad (contenido calificativo); "
            "solo se incluyen las primeras K. Ej: 20 = las 20 cuentas más negativas."
        ),
    )
    batch_size: int = Field(
        default=32,
        ge=1,
        le=512,
        description="Número de posts por lote. El endpoint siempre procesa por batches; este valor define el tamaño del lote (default 32).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "posts": [
                        {
                            "full_text": "El candidato Pérez es corrupto y mentiroso.",
                            "user_screen_name": "cuenta1",
                            "candidate_id": "perez",
                        },
                        {
                            "full_text": "Pérez y la diputada García son incompetentes.",
                            "user_screen_name": "cuenta1",
                            "candidate_id": "perez",
                        },
                        {
                            "full_text": "García hace un buen trabajo en educación.",
                            "user_screen_name": "cuenta2",
                            "candidate_id": "garcia",
                        },
                    ],
                    "candidate_entities": ["Pérez", "García"],
                    "top_negative_k": 20,
                    "batch_size": 32,
                }
            ]
        }
    }


class CorpusAnalysisResult(BaseModel):
    """Full result of NLP corpus analysis (entities, adjectives, accounts, clusters)."""

    entity_mentions: list[EntityMention] = Field(
        default_factory=list,
        description="Entities and mention counts",
    )
    adjectives_by_entity: list[AdjectivesByEntity] = Field(
        default_factory=list,
        description="Adjectives associated to each entity/candidate",
    )
    top_negative_accounts: list[TopNegativeAccount] = Field(
        default_factory=list,
        description="Most active accounts in negative/disinformation content",
    )
    account_clusters: list[AccountCluster] = Field(
        default_factory=list,
        description="Clusters of related operating accounts",
    )
    word_clusters_by_candidate: list[WordClusterByCandidate] = Field(
        default_factory=list,
        description="Word/adjective clusters per candidate",
    )
