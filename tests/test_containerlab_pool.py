import asyncio
import pytest
from unittest.mock import MagicMock, patch


def _make_healthy_client():
    transport = MagicMock()
    transport.is_active.return_value = True
    client = MagicMock()
    client.get_transport.return_value = transport
    return client


def _make_dead_client():
    transport = MagicMock()
    transport.is_active.return_value = False
    client = MagicMock()
    client.get_transport.return_value = transport
    return client


@pytest.mark.asyncio
async def test_pool_reuses_healthy_connection():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    client = _make_healthy_client()
    pool._pool.append(client)

    async with pool.acquire() as c:
        assert c is client


@pytest.mark.asyncio
async def test_pool_replaces_dead_connection():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    dead = _make_dead_client()
    fresh = _make_healthy_client()
    pool._pool.append(dead)

    with patch.object(pool, "_connect", return_value=fresh):
        async with pool.acquire() as c:
            assert c is fresh
    dead.close.assert_called_once()


@pytest.mark.asyncio
async def test_pool_creates_connection_when_empty():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    fresh = _make_healthy_client()

    with patch.object(pool, "_connect", return_value=fresh):
        async with pool.acquire() as c:
            assert c is fresh


@pytest.mark.asyncio
async def test_pool_returns_connection_after_use():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    fresh = _make_healthy_client()

    with patch.object(pool, "_connect", return_value=fresh):
        async with pool.acquire():
            pass
    assert len(pool._pool) == 1


@pytest.mark.asyncio
async def test_pool_respects_max_size():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    clients = [_make_healthy_client() for _ in range(2)]
    call_count = 0

    def make_client():
        nonlocal call_count
        c = clients[call_count]
        call_count += 1
        return c

    with patch.object(pool, "_connect", side_effect=make_client):
        async with pool.acquire() as c1:
            async with pool.acquire() as c2:
                # third acquire must wait; test that semaphore blocks
                acquired = False

                async def try_acquire():
                    nonlocal acquired
                    async with pool.acquire():
                        acquired = True

                task = asyncio.create_task(try_acquire())
                await asyncio.sleep(0.05)
                assert not acquired  # still waiting
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


@pytest.mark.asyncio
async def test_pool_releases_semaphore_on_connect_failure():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=1)

    with patch.object(pool, "_connect", side_effect=Exception("connection refused")):
        with pytest.raises(Exception, match="connection refused"):
            async with pool.acquire():
                pass

    # semaphore must be released — a second acquire should not hang
    fresh = _make_healthy_client()
    with patch.object(pool, "_connect", return_value=fresh):
        async with pool.acquire() as c:
            assert c is fresh
