"""Disabled template: adapt schema, tool name and request/response to the real API."""
import json
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from camara_server.config import required
from camara_server.core.api_client import GatewayApiClient
from camara_server.core.contracts import ApiModule, ModuleContext, ToolBinding


def create_module(context: ModuleContext) -> ApiModule:
    provider = context.provider_context
    client = GatewayApiClient(provider.http, context.authentication,
        required(provider.environment, context.settings["endpoint_env"]), provider.timeout)
    tool = Tool(name=context.settings.get("tool_name", "new_api_call"),
        description="Call an explicitly configured Open Gateway API operation.",
        input_schema={"type": "object", "properties": {"request": {"type": "object"}},
                      "required": ["request"], "additionalProperties": False},
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True))

    async def handle(arguments):
        response = await client.post_json(arguments["request"])
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(response.data))], structured_content=response.data)

    return ApiModule(context.id, (ToolBinding(tool, handle),))
