from importlib import import_module
import json
import tomllib
from typing import Mapping
from jsonschema import Draft202012Validator, ValidationError
from mcp import MCPError
from mcp.types import CallToolResult, TextContent, INVALID_PARAMS
from .contracts import ApiModule, ModuleContext, ProviderContext, ToolBinding
from .errors import ServiceError
from camara_server.diagnostics import operation, event, result_fields
import logging


def load_factory(reference: str):
    module_name, separator, name = reference.partition(":")
    if not separator or not module_name or not name:
        raise ValueError("Factory must have format python.module:function")
    factory = getattr(import_module(module_name), name)
    if not callable(factory):
        raise ValueError("Module factory must be callable")
    return factory


class AuthRegistry:
    def __init__(self, context: ProviderContext, profiles: Mapping):
        self.context, self.profiles = context, profiles
        self.instances = {}

    def resolve(self, name: str):
        if name not in self.profiles:
            raise ValueError(f"Unknown OAuth profile: {name}")
        if name not in self.instances:
            options = self.profiles[name]
            provider = load_factory(options["factory"])(self.context, options)
            if not callable(getattr(provider, "get", None)) or not callable(getattr(provider, "invalidate", None)):
                raise ValueError(f"OAuth profile {name} does not implement TokenProvider")
            self.instances[name] = provider
        return self.instances[name]

    async def aclose(self):
        import asyncio
        closers = [provider.aclose() for provider in self.instances.values()
                   if callable(getattr(provider, "aclose", None))]
        if closers:
            results = await asyncio.gather(*closers, return_exceptions=True)
            if any(isinstance(result, BaseException) for result in results):
                raise RuntimeError("OAuth provider shutdown failed")


class ToolRegistry:
    def __init__(self):
        self.bindings: dict[str, ToolBinding] = {}
        self.module_ids = []
        self.authentication = None
        self.prompts = {}
        self.resources = {}

    async def aclose(self):
        if self.authentication is not None:
            await self.authentication.aclose()

    def register(self, module: ApiModule):
        if module.id in self.module_ids:
            raise ValueError(f"Duplicate module ID: {module.id}")
        names = [binding.tool.name for binding in module.tools]
        if len(set(names)) != len(names) or set(names) & self.bindings.keys():
            raise ValueError(f"Duplicate tool name in module: {module.id}")
        prompt_names = [binding.prompt.name for binding in module.prompts]
        resource_uris = [str(binding.resource.uri) for binding in module.resources]
        if len(set(prompt_names)) != len(prompt_names) or set(prompt_names) & self.prompts.keys():
            raise ValueError(f"Duplicate prompt in module: {module.id}")
        if len(set(resource_uris)) != len(resource_uris) or set(resource_uris) & self.resources.keys():
            raise ValueError(f"Duplicate resource URI in module: {module.id}")
        for binding in module.tools:
            if binding.tool.input_schema.get("type") != "object":
                raise ValueError("Tool input schema must be an object")
            Draft202012Validator.check_schema(binding.tool.input_schema)
            if binding.tool.output_schema:
                Draft202012Validator.check_schema(binding.tool.output_schema)
        self.bindings.update({binding.tool.name: binding for binding in module.tools})
        self.module_ids.append(module.id)
        self.prompts.update({binding.prompt.name: binding for binding in module.prompts})
        self.resources.update({str(binding.resource.uri): binding for binding in module.resources})

    def list_prompts(self):
        return [self.prompts[name].prompt for name in sorted(self.prompts)]

    async def get_prompt(self, name, arguments):
        if name not in self.prompts:
            raise MCPError(INVALID_PARAMS, "Unknown prompt")
        binding = self.prompts[name]
        fields = binding.prompt.arguments or []
        if set(arguments) - {field.name for field in fields} or any(field.required and field.name not in arguments for field in fields):
            raise MCPError(INVALID_PARAMS, "Invalid prompt arguments")
        return await binding.handler(arguments)

    def list_resources(self):
        return [self.resources[uri].resource for uri in sorted(self.resources)]

    async def read_resource(self, uri):
        if uri not in self.resources:
            raise MCPError(INVALID_PARAMS, "Unknown resource")
        return await self.resources[uri].handler()

    def list_tools(self):
        return [self.bindings[name].tool for name in sorted(self.bindings)]

    async def call(self, name: str, arguments: dict):
        async with operation("tool.call", tool=name) as log:
            result = await self._call(name, arguments)
            log.update(**result_fields(result))
            return result

    async def _call(self, name: str, arguments: dict):
        if name not in self.bindings:
            raise MCPError(INVALID_PARAMS, "Unknown tool")
        binding = self.bindings[name]
        try:
            Draft202012Validator(binding.tool.input_schema).validate(arguments)
        except ValidationError:
            return self.error_result(ServiceError("INVALID_ARGUMENT"))
        try:
            result = await binding.handler(arguments)
            if not result.is_error and binding.tool.output_schema:
                Draft202012Validator(binding.tool.output_schema).validate(result.structured_content)
            return result
        except ServiceError as error:
            return self.error_result(error)
        except Exception as error:
            event("tool.handler_exception", logging.ERROR, exception_type=type(error).__name__)
            # Third-party modules must not leak credentials through exceptions.
            return self.error_result(ServiceError("INTERNAL_ERROR"))

    @staticmethod
    def error_result(error):
        payload = error.payload()
        return CallToolResult(is_error=True, content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structured_content=payload,
            _meta={"camara/untrustedUpstreamMessage": error.upstream_message} if error.upstream_message else None)


def load_registry(path, context: ProviderContext):
    with path.open("rb") as source:
        manifest = tomllib.load(source)
    authentication = AuthRegistry(context, manifest.get("auth", {}))
    tools = ToolRegistry()
    tools.authentication = authentication
    for options in manifest.get("modules", []):
        if not options.get("enabled", True):
            continue
        module_context = ModuleContext(options["id"], context, authentication.resolve(options["auth_profile"]), options)
        module = load_factory(options["factory"])(module_context)
        if not isinstance(module, ApiModule) or module.id != options["id"]:
            raise ValueError("API factory must return ApiModule with configured ID")
        tools.register(module)
    if not tools.bindings:
        raise ValueError("At least one API tool must be enabled")
    return tools
