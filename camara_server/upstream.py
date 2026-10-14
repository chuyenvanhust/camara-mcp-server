"""Compatibility facade; new integrations use core registry and API modules."""
from camara_server.config import ROOT
from camara_server.auth.client_credentials import build_private_key_jwt
from camara_server.core.api_client import GatewayApiClient
from camara_server.core.contracts import ProviderContext
from camara_server.core.errors import ServiceError
from camara_server.modules.sim_swap import SimSwapApi


class SimSwapService:
    def __init__(self, config, client):
        self.config, self.client = config, client
        self.provider = self.api = None

    def prepare(self):
        if self.provider is not None:
            return
        context = ProviderContext(ROOT, self.config.environment, self.client, self.config.bridge.timeout)
        self.provider = build_private_key_jwt(context, {'env_prefix':'UPSTREAM', 'include_client_id':False})
        self.api = SimSwapApi(GatewayApiClient(self.client, self.provider,
            self.config.environment['UPSTREAM_CHECK_URL'], self.config.bridge.timeout))

    async def token(self):
        self.prepare()
        return await self.provider.get()

    async def check(self, phone_number, max_age):
        self.prepare()
        return await self.api.check(phone_number, max_age)
