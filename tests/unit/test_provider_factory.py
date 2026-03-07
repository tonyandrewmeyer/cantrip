"""Tests for the LLM provider factory."""

from unittest.mock import MagicMock, patch

import pytest

from cantrip.llm import create_provider


class TestCreateProvider:
    """Tests for the create_provider factory."""

    def test_unknown_provider_raises(self):
        """Test that an unknown provider name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("unknown-provider")

    @patch("cantrip.llm.gemini.genai")
    def test_create_gemini_default(self, mock_genai):
        """Test creating a Gemini provider with defaults."""
        mock_genai.Client.return_value = MagicMock()

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            provider = create_provider("gemini")

        from cantrip.llm.gemini import GeminiProvider

        assert isinstance(provider, GeminiProvider)

    @patch("cantrip.llm.gemini.genai")
    def test_create_gemini_custom_model(self, mock_genai):
        """Test creating a Gemini provider with a custom model."""
        mock_genai.Client.return_value = MagicMock()

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            provider = create_provider("gemini", model="gemini-1.5-flash")

        assert provider.model_name == "gemini-1.5-flash"

    @patch("cantrip.llm.claude.anthropic")
    def test_create_claude_default(self, mock_anthropic):
        """Test creating a Claude provider with defaults."""
        mock_anthropic.AsyncAnthropic.return_value = MagicMock()

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            provider = create_provider("claude")

        from cantrip.llm.claude import ClaudeProvider

        assert isinstance(provider, ClaudeProvider)

    @patch("cantrip.llm.claude.anthropic")
    def test_create_claude_custom_model(self, mock_anthropic):
        """Test creating a Claude provider with a custom model."""
        mock_anthropic.AsyncAnthropic.return_value = MagicMock()

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            provider = create_provider("claude", model="claude-haiku-4-5-20251001")

        assert provider.model_name == "claude-haiku-4-5-20251001"

    @patch("cantrip.llm.inference_snap.InferenceSnapProvider._detect_model", return_value="test")
    @patch("cantrip.llm.inference_snap.discover_snap_endpoint", return_value="http://test/v1")
    def test_create_inference_snap_default(self, _mock_discover, _mock_detect):
        """Test creating an inference snap provider with defaults."""
        provider = create_provider("inference-snap")

        from cantrip.llm.inference_snap import InferenceSnapProvider

        assert isinstance(provider, InferenceSnapProvider)
        assert provider.snap_name == "gemma3"

    @patch("cantrip.llm.inference_snap.InferenceSnapProvider._detect_model", return_value="test")
    @patch("cantrip.llm.inference_snap.discover_snap_endpoint", return_value="http://test/v1")
    def test_create_inference_snap_custom(self, _mock_discover, _mock_detect):
        """Test creating an inference snap provider with a custom snap and model."""
        provider = create_provider("inference-snap", model="custom-model", snap_name="deepseek-r1")

        assert provider.snap_name == "deepseek-r1"
        assert provider.model_name == "custom-model"
