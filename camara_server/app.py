from contextlib import asynccontextmanager
import logging
from .diagnostics import configure, event
import httpx2 as httpx
from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (CallToolRequestParams, ListToolsResult, PaginatedRequestParams, INVALID_PARAMS,
    ListPromptsResult, GetPromptRequestParams, ListResourcesResult, ReadResourceRequestParams, ListResourceTemplatesResult)
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn
from camara_server.config import PROTOCOL_VERSION, ROOT, ServerConfig
from .transport import TransportMiddleware
from .core.contracts import ProviderContext
from .core.registry import ToolRegistry, load_registry


def make_server(registry: ToolRegistry):
    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None):
        if params and params.cursor:
            raise MCPError(INVALID_PARAMS, "Invalid cursor")
        return ListToolsResult(tools=registry.list_tools(), ttl_ms=30000, cache_scope="private")

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams):
        return await registry.call(params.name, params.arguments or {})

    async def list_prompts(ctx, params):
        if params and params.cursor:
            raise MCPError(INVALID_PARAMS, "Invalid cursor")
        return ListPromptsResult(prompts=registry.list_prompts(), ttl_ms=30000, cache_scope="private")

    async def get_prompt(ctx, params: GetPromptRequestParams):
        return await registry.get_prompt(params.name, params.arguments or {})

    async def list_resources(ctx, params):
        if params and params.cursor:
            raise MCPError(INVALID_PARAMS, "Invalid cursor")
        return ListResourcesResult(resources=registry.list_resources(), ttl_ms=30000, cache_scope="private")

    async def read_resource(ctx, params: ReadResourceRequestParams):
        return await registry.read_resource(str(params.uri))

    async def list_resource_templates(ctx, params):
        if params and params.cursor:
            raise MCPError(INVALID_PARAMS, "Invalid cursor")
        return ListResourceTemplatesResult(resource_templates=[], ttl_ms=30000, cache_scope="private")

    return Server("camara-open-gateway", version="0.6.0", on_list_tools=list_tools, on_call_tool=call_tool,
        on_list_prompts=list_prompts if registry.prompts else None, on_get_prompt=get_prompt if registry.prompts else None,
        on_list_resources=list_resources if registry.resources else None, on_read_resource=read_resource if registry.resources else None,
        on_list_resource_templates=list_resource_templates if registry.resources else None)


def create_app(config: ServerConfig, registry: ToolRegistry | None = None):
    http_client = httpx.AsyncClient(timeout=config.timeout, follow_redirects=False)
    registry = registry or load_registry(config.modules_file, ProviderContext(ROOT, config.environment, http_client, config.timeout))
    server = make_server(registry)
    app = server.streamable_http_app(json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=list(config.allowed_hosts), allowed_origins=list(config.allowed_origins)))
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with http_client, original_lifespan(app):
            try:
                yield
            finally:
                await registry.aclose()

    app.router.lifespan_context = lifespan
    async def health(request):
        return JSONResponse({"status": "ok", "mode": config.mode, "protocolVersion": PROTOCOL_VERSION, "modules": registry.module_ids})
    app.router.routes.append(Route("/health", health))
    return TransportMiddleware(app, config)


def main():
    configure(ROOT)
    try:
        config = ServerConfig.from_env()
        uvicorn.run(create_app(config), host=config.host, port=config.port,
            log_level=config.environment.get("LOG_LEVEL", "info").lower(), access_log=False)
    except Exception as error:
        event("server.startup_failed", logging.ERROR, exception_type=type(error).__name__)
        raise SystemExit(1) from None
    finally:
        event("process.stop")
