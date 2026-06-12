import asyncio
from typing import Any, ClassVar

import httpx


class GeminiTextResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"candidates": [{"content": {"parts": [{"text": self.text}]}}]}


class GeminiPayloadResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class TransientGeminiResponse:
    def raise_for_status(self) -> None:
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("Gemini overloaded", request=request, response=response)


class RecordingAsyncClient:
    posts: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *args, **kwargs) -> None:
        return None

    async def __aenter__(self):
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await asyncio.sleep(0)

    async def post(self, url: str, *, headers: dict, json: dict, **kwargs: Any):
        await asyncio.sleep(0)
        self._record_post(url=url, headers=headers, json=json, timeout=kwargs.get("timeout"))
        return self.response_for(json)

    def response_for(self, payload: dict):
        raise NotImplementedError

    def _record_post(self, *, url: str, headers: dict, json: dict, timeout: Any) -> None:
        self.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})


class TransientOnceAsyncClient(RecordingAsyncClient):
    async def post(self, url: str, *, headers: dict, json: dict, **kwargs: Any):
        await asyncio.sleep(0)
        self._record_post(url=url, headers=headers, json=json, timeout=kwargs.get("timeout"))
        if len(self.posts) == 1:
            return TransientGeminiResponse()
        return self.success_response_for(json)

    def success_response_for(self, payload: dict):
        raise NotImplementedError
