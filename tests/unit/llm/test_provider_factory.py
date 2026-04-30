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

    @patch("cantrip.llm.inference_snap.InferenceSnapProvider._probe_server")
    @patch("cantrip.llm.inference_snap.InferenceSnapProvider._detect_model", return_value="test")
    @patch("cantrip.llm.inference_snap.discover_snap_endpoint", return_value="http://test/v1")
    def test_create_inference_snap_custom(self, _mock_discover, _mock_detect, _mock_probe):
        """Test creating an inference snap provider with a custom snap and model."""
        provider = create_provider("inference-snap", model="custom-model", snap_name="deepseek-r1")

        assert provider.snap_name == "deepseek-r1"
        assert provider.model_name == "custom-model"

    @patch("cantrip.llm.fireworks.FireworksProvider._probe_capabilities")
    def test_create_fireworks_default(self, _mock_probe):
        """Default Fireworks provider uses the Kimi K2 agentic model."""
        with patch.dict("os.environ", {"FIREWORKS_API_KEY": "test-key"}):
            provider = create_provider("fireworks")

        from cantrip.llm.fireworks import DEFAULT_MODEL, FireworksProvider

        assert isinstance(provider, FireworksProvider)
        assert provider.model_name == DEFAULT_MODEL
        assert provider.base_url == "https://api.fireworks.ai/inference/v1"

    @patch("cantrip.llm.fireworks.FireworksProvider._probe_capabilities")
    def test_create_fireworks_custom_model(self, _mock_probe):
        """``--model`` overrides the Fireworks default."""
        with patch.dict("os.environ", {"FIREWORKS_API_KEY": "test-key"}):
            provider = create_provider("fireworks", model="accounts/fireworks/models/glm-5p1")

        assert provider.model_name == "accounts/fireworks/models/glm-5p1"

    def test_create_fireworks_requires_api_key(self):
        """Missing FIREWORKS_API_KEY surfaces an actionable ProviderError."""
        from cantrip.llm.base import ProviderError

        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ProviderError, match="FIREWORKS_API_KEY"),
        ):
            create_provider("fireworks")

    @patch("cantrip.llm.openrouter.OpenRouterProvider._probe_capabilities")
    def test_create_openrouter_default(self, _mock_probe):
        """Default OpenRouter provider uses openai/gpt-4o."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            provider = create_provider("openrouter")

        from cantrip.llm.openrouter import DEFAULT_MODEL, OpenRouterProvider

        assert isinstance(provider, OpenRouterProvider)
        assert provider.model_name == DEFAULT_MODEL
        assert provider.base_url == "https://openrouter.ai/api/v1"

    @patch("cantrip.llm.openrouter.OpenRouterProvider._probe_capabilities")
    def test_create_openrouter_custom_model(self, _mock_probe):
        """``--model`` overrides the OpenRouter default."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            provider = create_provider("openrouter", model="meta-llama/llama-3.3-70b-instruct")

        assert provider.model_name == "meta-llama/llama-3.3-70b-instruct"

    def test_create_openrouter_requires_api_key(self):
        """Missing OPENROUTER_API_KEY surfaces an actionable ProviderError."""
        from cantrip.llm.base import ProviderError

        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ProviderError, match="OPENROUTER_API_KEY"),
        ):
            create_provider("openrouter")

    @patch("cantrip.llm.openai_compatible.OpenAICompatibleProvider._probe_context_window")
    def test_create_openai_compatible(self, _mock_probe):
        """openai-compatible requires base_url + model and picks them up."""
        with patch.dict("os.environ", {"OPENAI_COMPATIBLE_API_KEY": "test-key"}):
            provider = create_provider(
                "openai-compatible",
                model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                base_url="https://api.together.xyz/v1",
            )

        from cantrip.llm.openai_compatible import OpenAICompatibleProvider

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://api.together.xyz/v1"
        assert provider.model_name == "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    def test_create_openai_compatible_requires_base_url(self):
        """openai-compatible without --base-url fails before constructing."""
        with pytest.raises(ValueError, match="base-url"):
            create_provider("openai-compatible", model="some-model")

    def test_create_openai_compatible_requires_model(self):
        """openai-compatible without --model fails before constructing."""
        with pytest.raises(ValueError, match="model"):
            create_provider("openai-compatible", base_url="https://example.com/v1")
