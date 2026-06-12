from unittest.mock import AsyncMock, patch

import pytest

from app.services.redis_cache import get_cached_data, invalidate_cache, set_cached_data


@pytest.mark.asyncio
async def test_get_cached_data_miss():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("app.services.redis_cache.Redis.from_url") as mock_from_url:
        mock_from_url.return_value.__aenter__.return_value = mock_redis

        res = await get_cached_data("test-key")
        assert res is None
        mock_redis.get.assert_called_once_with("test-key")


@pytest.mark.asyncio
async def test_get_cached_data_hit():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = '{"foo": "bar"}'

    with patch("app.services.redis_cache.Redis.from_url") as mock_from_url:
        mock_from_url.return_value.__aenter__.return_value = mock_redis

        res = await get_cached_data("test-key")
        assert res == {"foo": "bar"}
        mock_redis.get.assert_called_once_with("test-key")


@pytest.mark.asyncio
async def test_set_cached_data():
    mock_redis = AsyncMock()

    with patch("app.services.redis_cache.Redis.from_url") as mock_from_url:
        mock_from_url.return_value.__aenter__.return_value = mock_redis

        await set_cached_data("test-key", {"hello": "world"}, ttl=120)
        mock_redis.set.assert_called_once_with("test-key", '{"hello": "world"}', ex=120)


@pytest.mark.asyncio
async def test_invalidate_cache():
    mock_redis = AsyncMock()

    with patch("app.services.redis_cache.Redis.from_url") as mock_from_url:
        mock_from_url.return_value.__aenter__.return_value = mock_redis

        await invalidate_cache("key1", "key2")
        assert mock_redis.delete.call_count == 2
        mock_redis.delete.assert_any_call("key1")
        mock_redis.delete.assert_any_call("key2")
