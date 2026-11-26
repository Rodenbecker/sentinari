import unittest
from unittest.mock import patch

from app.llm_gateway import OpenAICompatibleProvider


class OpenAICompatibleLocalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.provider = OpenAICompatibleProvider(
            {
                "openai_compatible": {
                    "base_url": "http://127.0.0.1:8101/v1",
                    "chat_model": "gemma-local.gguf",
                    "embedding_base_url": "http://127.0.0.1:8102/v1",
                    "embedding_model": "qwen-embed.gguf",
                    "api_key_env": "SENTINARI_TEST_LOCAL_API_KEY",
                }
            }
        )

    @patch("app.llm_gateway.requests.post")
    def test_chat_uses_chat_base_url(self, post):
        response = post.return_value
        response.json.return_value = {
            "choices": [{"message": {"content": "ready"}}]
        }

        result = self.provider.chat([{"role": "user", "content": "test"}])

        self.assertEqual(result, "ready")
        self.assertEqual(
            post.call_args.args[0],
            "http://127.0.0.1:8101/v1/chat/completions",
        )

    @patch("app.llm_gateway.requests.post")
    def test_embeddings_use_separate_embedding_base_url(self, post):
        response = post.return_value
        response.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}

        result = self.provider.embed("test")

        self.assertEqual(result, [0.1, 0.2])
        self.assertEqual(
            post.call_args.args[0],
            "http://127.0.0.1:8102/v1/embeddings",
        )


if __name__ == "__main__":
    unittest.main()
