"""OpenAI Embeddings implementation."""

import logging
import os
import time

from openai import AsyncOpenAI

from ..base import BaseEmbedder

logger = logging.getLogger(__name__)


class OpenAIEmbedder(BaseEmbedder):
    """Embedder using OpenAI's embedding API."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
        batch_size: int = 100,
        dimensions: int | None = None,
        max_retries: int = 2,
        timeout: float = 60.0,
        batch_delay: float = 3.0,
    ):
        """Initialize OpenAI embedder.

        Args:
            model: OpenAI embedding model name
                - text-embedding-3-small (default, 1536 dims, cheaper)
                - text-embedding-3-large (3072 dims, better performance)
                - text-embedding-ada-002 (legacy, 1536 dims)
            api_key: OpenAI API key (defaults to UTU_EMBEDDING_API_KEY env var)
            base_url: Custom base URL for OpenAI-compatible services
            batch_size: Maximum batch size for API calls
            dimensions: Explicit embedding dimension for providers that support it
            max_retries: Maximum number of retries on failure
            timeout: Request timeout in seconds
            batch_delay: Delay in seconds between batches to avoid rate limiting
        """
        self.model = model
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.dimensions = dimensions
        self.usage_records: list[dict[str, int | float | str]] = []

        # Initialize OpenAI client
        self.client = AsyncOpenAI(
            api_key=api_key or os.getenv("UTU_EMBEDDING_API_KEY"),
            base_url=base_url,
            max_retries=max_retries,
            timeout=timeout,
        )

        logger.info(
            f"Initialized OpenAIEmbedder with model: {self.model}, "
            f"batch_size: {self.batch_size}, dimensions: {self.dimensions}, "
            f"batch_delay: {self.batch_delay}s"
        )

    def _request_kwargs(self, input_value: str | list[str]) -> dict:
        kwargs = {
            "model": self.model,
            "input": input_value,
            "encoding_format": "float",
        }
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions
        return kwargs

    def _validate_embeddings(self, embeddings: list[list[float]], expected_count: int) -> None:
        if len(embeddings) != expected_count:
            raise ValueError(
                f"Embedding response count mismatch: expected {expected_count}, got {len(embeddings)}"
            )
        if self.dimensions is not None and any(len(vector) != self.dimensions for vector in embeddings):
            raise ValueError(f"Embedding response dimension mismatch: expected {self.dimensions}")

    def _record_usage(self, response, item_count: int, latency_ms: float) -> None:
        usage = getattr(response, "usage", None)
        input_tokens = int(
            getattr(usage, "prompt_tokens", None)
            or getattr(usage, "input_tokens", None)
            or getattr(usage, "total_tokens", None)
            or 0
        )
        total_tokens = int(getattr(usage, "total_tokens", None) or input_tokens)
        record = {
            "model": self.model,
            "item_count": item_count,
            "input_tokens": input_tokens,
            "total_tokens": total_tokens,
            "latency_ms": round(latency_ms, 3),
            "estimated_cost_cny": input_tokens * 0.5 / 1_000_000,
        }
        self.usage_records.append(record)
        logger.info(
            "Embedding usage: model=%s, items=%s, input_tokens=%s, latency_ms=%.1f",
            self.model,
            item_count,
            input_tokens,
            latency_ms,
        )

    def _batched(self, iterable, n):
        """Split iterable into batches of size n."""
        from itertools import islice

        if n < 1:
            raise ValueError("n must be at least one")
        it = iter(iterable)
        while batch := tuple(islice(it, n)):
            yield batch

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        embeddings = []

        try:
            # Calculate total batches for progress tracking
            batches = list(self._batched(texts, self.batch_size))
            total_batches = len(batches)

            for i, batch in enumerate(batches):
                logger.info(f"Processing batch {i + 1}/{total_batches} with {len(batch)} texts...")

                logger.info(
                    "Embedding API request: model=%s, batch_size=%s, dimensions=%s",
                    self.model,
                    len(batch),
                    self.dimensions,
                )
                started = time.perf_counter()
                response = await self.client.embeddings.create(**self._request_kwargs(list(batch)))
                latency_ms = (time.perf_counter() - started) * 1000
                ordered = sorted(response.data, key=lambda item: item.index)
                batch_embeddings = [item.embedding for item in ordered]
                self._validate_embeddings(batch_embeddings, len(batch))
                self._record_usage(response, len(batch), latency_ms)
                embeddings.extend(batch_embeddings)
                logger.info("Successfully received %s embeddings from API", len(batch_embeddings))

                # Add delay between batches to avoid rate limiting (except for last batch)
                if i < total_batches - 1 and self.batch_delay > 0:
                    logger.debug(f"Waiting {self.batch_delay}s before next batch...")
                    import asyncio

                    await asyncio.sleep(self.batch_delay)

            logger.info(f"✓ Successfully generated {len(embeddings)} embeddings")
            return embeddings

        except Exception:
            logger.error("Error generating embeddings (details suppressed)")
            raise

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query.

        Args:
            query: Query text to embed

        Returns:
            Embedding vector
        """
        try:
            # Call OpenAI embedding API for single query
            started = time.perf_counter()
            response = await self.client.embeddings.create(**self._request_kwargs(query))
            latency_ms = (time.perf_counter() - started) * 1000

            embedding = response.data[0].embedding
            self._validate_embeddings([embedding], 1)
            self._record_usage(response, 1, latency_ms)

            logger.info("✓ Successfully generated embedding for query")
            return embedding

        except Exception:
            logger.error("Error generating query embedding (details suppressed)")
            raise
