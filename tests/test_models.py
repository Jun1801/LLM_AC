from __future__ import annotations

from app.embedding import EmbeddingService
from app.validation import ValidationService


class FakeEmbeddingModel:
    def encode_query(self, text, **kwargs):
        return [0.25] * 384

    def get_sentence_embedding_dimension(self):
        return 384


class FakeCrossEncoder:
    def __init__(self, model_id, **kwargs):
        self.model_id = model_id

    def predict(self, pairs):
        query, cached = pairs[0]
        if "quarterly finance report" in query and "quarterly report for finance" in cached:
            return [3.5]
        return [-3.5]


def test_embedding_service_returns_expected_dimension():
    service = EmbeddingService(
        model_id="fake-embedding",
        expected_dim=384,
        _model=FakeEmbeddingModel(),
    )
    vector = service.encode("Need access to quarterly finance report")
    assert len(vector) == 384
    assert all(isinstance(value, float) for value in vector)


def test_validation_service_scores_related_text_higher(monkeypatch):
    monkeypatch.setattr("app.validation.CrossEncoder", FakeCrossEncoder)
    service = ValidationService(
        model_id="fake-cross-encoder",
        threshold=0.8,
    )
    positive = service.validate(
        "Need access to quarterly finance report",
        "Need access to quarterly report for finance",
    )
    negative = service.validate(
        "Need access to quarterly finance report",
        "Please reset the VPN token for my laptop",
    )
    assert positive.score > negative.score
    assert positive.is_hit is True
    assert negative.is_hit is False
