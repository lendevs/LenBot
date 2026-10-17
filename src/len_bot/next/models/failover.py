"""Ordered backup providers for one role, with a circuit breaker per provider/model.

Only roles whose binding lists ``fallbacks`` use this; every other role keeps one ``ChatModel``
and fails as before. A candidate is left for the next one only on errors another provider may not
have (transport errors, timeouts, HTTP 401/403/408/409/425/429 and 5xx). A request the provider
understood and refused (other 4xx) or a malformed reply is raised at once: sending it elsewhere
would hide the cause.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import logging
import threading
import time
from typing import Literal

import httpx

from ..configuration.models import Binding, Failover, Models
from ..runtime.logs import error_text, log_event
from .client import ChatModel, ModelHTTPError, ModelReply, ModelSettings

logger = logging.getLogger(__name__)

FAILOVER_STATUS = frozenset({401, 403, 408, 409, 425, 429})


def failover_worthy(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, httpx.TransportError)):
        return True
    if isinstance(error, ModelHTTPError) and error.status_code is not None:
        return error.status_code in FAILOVER_STATUS or error.status_code >= 500
    return False


@dataclass
class Circuit:
    provider: str
    model: str
    state: Literal['closed', 'open', 'half_open'] = 'closed'
    consecutive_failures: int = 0
    open_until: float | None = None
    successes: int = 0
    failures: int = 0
    last_error: str | None = None
    last_error_at: float | None = None
    last_success_at: float | None = None


class ProviderHealth:
    """Circuits keyed by (role, provider, model); shared by every request of the process."""

    def __init__(self, settings: Failover | None = None, *, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time):
        self.settings = Failover() if settings is None else settings
        self.clock, self.wall = clock, wall
        self.circuits: dict[tuple[str, str, str], Circuit] = {}
        self.roles: dict[str, list[tuple[str, str]]] = {}
        self.served: dict[str, dict] = {}
        self._lock = threading.Lock()

    def configure(self, settings: Failover) -> None:
        self.settings = settings

    def register(self, role: str, candidates: list[tuple[str, str]]) -> None:
        with self._lock:
            self.roles[role] = list(candidates)
            for provider, model in candidates:
                self.circuits.setdefault((role, provider, model), Circuit(provider, model))

    def _refresh(self, circuit: Circuit) -> None:
        if circuit.state == 'open' and circuit.open_until is not None and self.clock() >= circuit.open_until:
            circuit.state = 'half_open'

    def order(self, role: str) -> list[int]:
        """Candidate indexes to try: closed or cooled-down ones by priority, then still-open ones by reopening time."""
        with self._lock:
            ready, waiting = [], []
            for index, (provider, model) in enumerate(self.roles[role]):
                circuit = self.circuits[(role, provider, model)]
                self._refresh(circuit)
                (waiting if circuit.state == 'open' else ready).append((circuit.open_until or 0, index))
            # Every circuit open: still try, soonest to reopen first, rather than refusing the turn.
            return [index for _, index in ready] + [index for _, index in sorted(waiting)]

    def succeeded(self, role: str, provider: str, model: str) -> None:
        with self._lock:
            circuit = self.circuits[(role, provider, model)]
            circuit.state, circuit.consecutive_failures, circuit.open_until = 'closed', 0, None
            circuit.successes += 1
            circuit.last_success_at = self.wall()

    def failed(self, role: str, provider: str, model: str, error: BaseException) -> Circuit:
        with self._lock:
            circuit = self.circuits[(role, provider, model)]
            circuit.failures += 1
            circuit.consecutive_failures += 1
            circuit.last_error, circuit.last_error_at = error_text(error), self.wall()
            # A failed trial after cooldown reopens at once; a closed circuit opens at the threshold.
            if circuit.state == 'half_open' or circuit.consecutive_failures >= self.settings.failure_threshold:
                circuit.state = 'open'
                circuit.open_until = self.clock() + self.settings.cooldown_seconds
            return circuit

    def record_served(self, role: str, served: dict) -> None:
        with self._lock:
            self.served[role] = {**served, 'at': self.wall()}

    def state(self) -> dict:
        with self._lock:
            now = self.clock()
            roles = {}
            for role, candidates in self.roles.items():
                rows = []
                for priority, (provider, model) in enumerate(candidates):
                    circuit = self.circuits[(role, provider, model)]
                    self._refresh(circuit)
                    rows.append({'priority': priority, 'provider': provider, 'model': model,
                                 'state': circuit.state, 'consecutive_failures': circuit.consecutive_failures,
                                 'reopens_in_seconds': (None if circuit.state != 'open' or circuit.open_until is None
                                                        else max(0.0, round(circuit.open_until - now, 3))),
                                 'successes': circuit.successes, 'failures': circuit.failures,
                                 'last_error': circuit.last_error, 'last_error_at': circuit.last_error_at,
                                 'last_success_at': circuit.last_success_at})
                roles[role] = {'candidates': rows, 'last_served': self.served.get(role)}
            return {'failure_threshold': self.settings.failure_threshold,
                    'cooldown_seconds': self.settings.cooldown_seconds, 'roles': roles}


# The host's circuits; the panel reads the same instance.
HEALTH = ProviderHealth()


class FailoverModel:
    """``ChatModel``'s interface over the primary binding and its fallbacks."""

    def __init__(self, role: str, candidates: list[tuple[str, ModelSettings]], health: ProviderHealth = HEALTH):
        self.role, self.health = role, health
        self.candidates = candidates
        self.models = [ChatModel(settings) for _, settings in candidates]
        health.register(role, [(provider, settings.model) for provider, settings in candidates])

    @property
    def settings(self) -> ModelSettings:
        """The primary's settings: request records and estimates describe the configured binding."""
        return self.candidates[0][1]

    async def __aenter__(self) -> FailoverModel:
        return self

    async def __aexit__(self, *_: object) -> None:
        for model in self.models:
            await model.__aexit__(None, None, None)

    async def complete(self, messages: list[dict], tools: list[dict], *,
                       max_output_tokens: int | None = None, session_id: str | None = None) -> ModelReply:
        attempts: list[dict] = []
        failure: BaseException | None = None
        for index in self.health.order(self.role):
            provider, settings = self.candidates[index]
            try:
                reply = await self.models[index].complete(messages, tools, max_output_tokens=max_output_tokens,
                                                          session_id=session_id)
            except Exception as error:
                if not failover_worthy(error):
                    raise
                circuit = self.health.failed(self.role, provider, settings.model, error)
                attempts.append({'provider': provider, 'model': settings.model, 'error': error_text(error)})
                log_event(logger, 'model_failover', f'{self.role} 模型 {provider}/{settings.model} 失败，尝试下一个',
                          level=logging.WARNING, role=self.role, provider=provider, model=settings.model,
                          priority=index, circuit=circuit.state, error=error)
                if failure is not None:
                    error.__context__ = failure
                failure = error
                continue
            self.health.succeeded(self.role, provider, settings.model)
            served = {'provider': provider, 'model': settings.model, 'priority': index, 'failed_before': attempts}
            self.health.record_served(self.role, served)
            return replace(reply, served_by=served)
        failure.add_note('所有备用模型都失败：' + '; '.join(
            f"{item['provider']}/{item['model']}: {item['error']}" for item in attempts))
        raise failure


def open_model(models: Models, role: str, health: ProviderHealth = HEALTH) -> ChatModel | FailoverModel:
    """One role's model: a plain ``ChatModel`` unless its binding lists fallbacks."""
    binding: Binding = getattr(models.roles, role)
    if binding is None:
        raise ValueError(f"models.roles.{role} is not configured")
    if not binding.fallbacks:
        return ChatModel(ModelSettings.from_binding(models.providers[binding.provider], binding))
    health.configure(models.failover)
    return FailoverModel(role, [(candidate.provider, ModelSettings.from_binding(models.providers[candidate.provider],
                                                                                candidate))
                                for candidate in binding.candidates()], health)
