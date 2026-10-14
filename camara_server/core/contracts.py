from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol
import httpx2 as httpx
from mcp.types import CallToolResult, Tool, Prompt, GetPromptResult, Resource, ReadResourceResult


class TokenProvider(Protocol):
    async def get(self) -> str: ...
    def invalidate(self, token: str) -> None: ...


@dataclass(frozen=True)
class ProviderContext:
    root: Path
    environment: Mapping[str, str]
    http: httpx.AsyncClient
    timeout: float


@dataclass(frozen=True)
class ToolBinding:
    tool: Tool
    handler: Callable[[dict[str, Any]], Awaitable[CallToolResult]]


@dataclass(frozen=True)
class PromptBinding:
    prompt: Prompt
    handler: Callable[[dict[str, str]], Awaitable[GetPromptResult]]


@dataclass(frozen=True)
class ResourceBinding:
    resource: Resource
    handler: Callable[[], Awaitable[ReadResourceResult]]


@dataclass(frozen=True)
class ApiModule:
    id: str
    tools: tuple[ToolBinding, ...]
    prompts: tuple[PromptBinding, ...] = ()
    resources: tuple[ResourceBinding, ...] = ()


@dataclass(frozen=True)
class ModuleContext:
    id: str
    provider_context: ProviderContext
    authentication: TokenProvider
    settings: Mapping[str, Any]
