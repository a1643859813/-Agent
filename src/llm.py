from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from .types import LLMReply, ToolCall


class DeepSeekClient:
    """Small OpenAI-compatible client; the Agent loop remains implemented locally."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def _request(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("Missing DEEPSEEK_API_KEY. Copy .env.example values into your environment.")
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools is not None:
            # 传入工具 Schema 后，DeepSeek 才能返回 OpenAI-compatible tool_calls。
            payload.update({"tools": tools, "tool_choice": "auto"})
        request = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"DeepSeek API failed ({exc.code}): {exc.read().decode(errors='replace')}") from exc

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMReply:
        return ToolCallParser.parse(self._request(messages, tools)["choices"][0]["message"])

    def summarize(self, previous_summary: str, old_messages: list[dict[str, Any]]) -> str:
        # 摘要请求不传工具，避免模型在压缩历史时触发业务工具调用。
        source = [{"role": item["role"], "content": item.get("content", "")[:500]} for item in old_messages if item["role"] in {"user", "assistant", "tool"}]
        prompt = ("Compress the conversation into JSON only. Required keys: goals, conclusions, open_items, preferences. "
                  "Each value must be a JSON array of concise strings. Preserve only durable task state; do not invent facts.\n"
                  f"Previous summary: {previous_summary}\nMessages: {json.dumps(source, ensure_ascii=False)}")
        content = self._request([{"role": "system", "content": "You produce valid JSON and nothing else."}, {"role": "user", "content": prompt}])["choices"][0]["message"].get("content", "{}")
        return StructuredSummary.normalise(content)


class StructuredSummary:
    KEYS = ("goals", "conclusions", "open_items", "preferences")

    @classmethod
    def normalise(cls, text: str) -> str:
        # 校验并补齐 JSON 键，保证 Runtime 后续拿到稳定的摘要结构。
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
        value = json.loads(clean)
        if not isinstance(value, dict):
            raise ValueError("summary is not a JSON object")
        result = {key: [str(item) for item in value.get(key, [])][:8] for key in cls.KEYS}
        return json.dumps(result, ensure_ascii=False)


class ToolCallParser:
    @staticmethod
    def parse(message: dict[str, Any]) -> LLMReply:
        calls = []
        for call in message.get("tool_calls") or []:
            # 标准 function calling：解析模型给出的工具名和 JSON 参数。
            fn = call["function"]
            calls.append(ToolCall(call.get("id", f"call_{len(calls)}"), fn["name"], json.loads(fn.get("arguments") or "{}")))
        content = message.get("content") or ""
        if not calls:
            # 兼容模型偶尔以 Markdown JSON 而非原生 tool_calls 输出的情况。
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
            if match:
                try:
                    item = json.loads(match.group(1))
                    if "tool" in item:
                        calls.append(ToolCall("text_call_0", item["tool"], item.get("arguments", {})))
                except json.JSONDecodeError:
                    pass
        return LLMReply(content=content, tool_calls=calls)
