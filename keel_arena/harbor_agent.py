"""Keel's installed-agent adapter for the pinned optional Harbor SDK."""

import hashlib
import json
import shlex
from importlib.metadata import version
from pathlib import Path

if version('harbor') != '0.26.0':
    raise ImportError('Keel Arena requires harbor==0.26.0')

from harbor.agents.agent_auth_resolution import ModelConnectionSpec, ProviderAccess
from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.base import ApiError, BaseInstalledAgent, NonZeroAgentExitCodeError, with_prompt_template
from harbor.models.model_api_format import ModelApiFormat

from .runtime import validate_config


class AgentTimeoutError(TimeoutError):
    """Named consistently with Harbor's reviewed timeout policy."""


class KeelAgent(BaseInstalledAgent):
    capabilities = AgentCapabilities(base_url=True)
    MODEL_CONNECTION = ModelConnectionSpec(
        default_provider='openai',
        agent_provider_access=ProviderAccess(api_key_candidate_names=['KEEL_API_KEY', 'OPENAI_API_KEY'],
                                             base_url_candidate_names=['KEEL_BASE_URL', 'OPENAI_BASE_URL']),
        api_key_destination_names={'default': 'KEEL_API_KEY'},
        base_url_destination_names={'default': 'KEEL_BASE_URL'},
        supported_api_formats=[ModelApiFormat.OPENAI_CHAT_COMPLETIONS],
        default_api_format_by_provider={'default': ModelApiFormat.OPENAI_CHAT_COMPLETIONS},
    )

    def __init__(self, *args, binary_path, binary_sha256, max_model_requests=12,
                 max_output_tokens=4096, context_tokens=16384, timeout_seconds=300,
                 temperature=0.0, top_p=1.0, seed=0, thinking=None, **kwargs):
        if thinking is not None and type(thinking) is not bool:
            raise ValueError('thinking must be a boolean or null in the job config')
        self.binary_path = Path(binary_path)
        if self.binary_path.is_symlink() or not self.binary_path.is_file():
            raise ValueError('binary_path must name a regular local executable')
        with self.binary_path.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != binary_sha256:
                raise ValueError('local binary digest mismatch')
        self.runtime_policy = dict(binary='/installed-agent/keel', binary_sha256=binary_sha256,
                                   root='/workspace', home='/installed-agent/arena-home',
                                   logs='/logs/agent/run', model='pending', base_url='http://localhost/v1',
                                   max_model_requests=max_model_requests, max_output_tokens=max_output_tokens,
                                   context_tokens=context_tokens, timeout_seconds=timeout_seconds,
                                   temperature=temperature, top_p=top_p, seed=seed, thinking=thinking)
        validate_config(self.runtime_policy)
        super().__init__(*args, **kwargs)
        if self.mcp_servers or self.skills_dir:
            raise ValueError('MCP servers and injected skills are not supported by this adapter')

    @staticmethod
    def name():
        return 'keel-arena'

    def get_version_command(self):
        return '/installed-agent/keel --version'

    async def install(self, environment):
        # User-supplied binary stays private; never download private releases,
        # copy credentials, build Keel, or change anything on the host.
        await environment.upload_file(self.binary_path, '/installed-agent/keel')
        await self.exec_as_root(environment, 'chmod 755 /installed-agent/keel')

    async def configure(self, environment):
        expected = self.runtime_policy['binary_sha256']
        await self.exec_as_agent(environment,
                                 f'test "$(sha256sum /installed-agent/keel | cut -d\' \' -f1)" = {shlex.quote(expected)}')
        await environment.upload_file(Path(__file__).with_name('runtime.py'), '/installed-agent/arena-runtime.py')

    @with_prompt_template
    async def run(self, instruction, environment, context):
        connection = self.model_connection
        config = dict(self.runtime_policy, model=connection.model_id,
                      base_url=connection.execution_base_url,
                      logs=str(self.environment_logs_dir / 'run'))
        validate_config(config)
        await self._upload_config_text(environment, content=json.dumps(config),
                                       remote_path='/installed-agent/arena-run.json', filename='arena-run.json')
        # Secret values go through Harbor's scoped environment, never shell argv.
        error = None
        try:
            await self.exec_as_agent(
                environment,
                command='python3 /installed-agent/arena-runtime.py --config /installed-agent/arena-run.json',
                env={**connection.env, 'ARENA_INSTRUCTION': instruction},
                cwd='/workspace', timeout_sec=config['timeout_seconds'] + 10)
        except NonZeroAgentExitCodeError as exc:
            error = exc
        result = await environment.exec(
            command='cat ' + shlex.quote(str(self.environment_logs_dir / 'run/runtime.json')))
        if result.return_code != 0:
            raise RuntimeError('runtime evidence unavailable')
        metadata = json.loads(result.stdout)
        status = metadata.get('status')
        if status == 'provider_error':
            raise ApiError('Arena provider failure; private evidence retained')
        if status == 'timeout':
            raise AgentTimeoutError('Arena wall-clock budget exhausted')
        if status in ('launch_error', 'cancelled'):
            raise RuntimeError('Arena execution environment failed')
        if status not in ('completed', 'agent_error', 'budget_exhausted'):
            raise RuntimeError('unknown Arena execution status')
        if error is not None:
            raise error
        if status != 'completed':
            raise NonZeroAgentExitCodeError('Arena agent budget or execution failure')

    def populate_context_post_run(self, context):
        path = self.logs_dir / 'run/runtime.json'
        if not path.is_file() or path.is_symlink():
            return
        with path.open('rb') as source:
            raw = source.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('runtime evidence too large')
        data = json.loads(raw)
        for key in ('input_tokens', 'output_tokens'):
            if data.get(key) is not None and (type(data[key]) is not int or data[key] < 0):
                raise ValueError('invalid runtime usage')
        context.n_input_tokens = data.get('input_tokens')
        context.n_output_tokens = data.get('output_tokens')
        context.metadata = {**(context.metadata or {}), 'arena_runtime': data}
