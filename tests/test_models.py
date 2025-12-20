"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from trust_api.models import ArticleInput, Metric


class TestArticleInput:
    """Tests for ArticleInput model."""

    def test_valid_article_input(self):
        """Test creating a valid ArticleInput."""
        article = ArticleInput(
            body="Test body",
            title="Test title",
            author="Test author",
            link="https://example.com",
            date="2024-01-15",
            media_type="news",
        )
        assert article.body == "Test body"
        assert article.title == "Test title"
        assert article.author == "Test author"
        assert article.link == "https://example.com"
        assert article.date == "2024-01-15"
        assert article.media_type == "news"

    def test_article_input_missing_fields(self):
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError):
            ArticleInput(
                body="Test body",
                title="Test title",
                # Missing required fields
            )

    def test_article_input_empty_strings(self):
        """Test that empty strings are allowed (validation happens at API level)."""
        article = ArticleInput(
            body="",
            title="",
            author="",
            link="",
            date="",
            media_type="",
        )
        assert article.body == ""
        assert article.title == ""


class TestMetric:
    """Tests for Metric model."""

    def test_valid_metric(self):
        """Test creating a valid Metric."""
        metric = Metric(
            id=0,
            criteria_name="Test Criteria",
            explanation="Test explanation",
            flag=1,
            score=0.85,
        )
        assert metric.id == 0
        assert metric.criteria_name == "Test Criteria"
        assert metric.explanation == "Test explanation"
        assert metric.flag == 1
        assert metric.score == 0.85

    def test_metric_flag_values(self):
        """Test that flag accepts only -1, 0, or 1."""
        # Valid flags
        Metric(id=0, criteria_name="Test", explanation="Test", flag=-1, score=0.5)
        Metric(id=0, criteria_name="Test", explanation="Test", flag=0, score=0.5)
        Metric(id=0, criteria_name="Test", explanation="Test", flag=1, score=0.5)

        # Invalid flag
        with pytest.raises(ValidationError):
            Metric(
                id=0,
                criteria_name="Test",
                explanation="Test",
                flag=2,  # Invalid
                score=0.5,
            )

    def test_metric_score_range(self):
        """Test that score must be between 0.0 and 1.0."""
        # Valid scores
        Metric(id=0, criteria_name="Test", explanation="Test", flag=0, score=0.0)
        Metric(id=0, criteria_name="Test", explanation="Test", flag=0, score=0.5)
        Metric(id=0, criteria_name="Test", explanation="Test", flag=0, score=1.0)

        # Invalid scores
        with pytest.raises(ValidationError):
            Metric(
                id=0,
                criteria_name="Test",
                explanation="Test",
                flag=0,
                score=-0.1,  # Below minimum
            )

        with pytest.raises(ValidationError):
            Metric(
                id=0,
                criteria_name="Test",
                explanation="Test",
                flag=0,
                score=1.1,  # Above maximum
            )

    def test_metric_missing_fields(self):
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError):
            Metric(
                id=0,
                criteria_name="Test",
                # Missing required fields
            )
