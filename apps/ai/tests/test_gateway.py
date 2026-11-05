import asyncio

from bjk_ai.gateway import GeminiGateway


def test_gemini_client_is_recreated_per_event_loop():
    gateway = GeminiGateway("test-key")

    async def clients_in_one_loop():
        return gateway._aio(), gateway._aio()

    first, same = asyncio.run(clients_in_one_loop())
    second, _ = asyncio.run(clients_in_one_loop())

    assert first is same
    assert first is not second
