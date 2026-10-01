"""Per-call Anthropic usage logging.

Every Claude call PartsBin makes goes through claude_parser._client(), which
wraps the SDK client in TrackedClient. After each messages.create (plain or
beta) one JSON line is appended to USAGE_LOG with the purpose, token counts,
server-tool counts and an estimated list-price cost. Ship the file to a log
pipeline/SIEM to make spend searchable and to alert on unusually expensive calls.

Logging must never break a call: every failure in here is swallowed.
"""

import json
import os
import time
from datetime import datetime, timezone

USAGE_LOG = os.getenv('PARTSBIN_USAGE_LOG', '/var/log/partsbin/anthropic-usage.log')

# USD per million tokens: (input, output, cache_read, cache_write_5m).
# List prices; update when the model or Anthropic's price sheet changes.
PRICES = {
    'claude-sonnet-5': (2.00, 10.00, 0.20, 2.50),
    'claude-sonnet-5-5': (2.00, 10.00, 0.20, 2.50),
    'claude-haiku-4-5': (1.00, 5.00, 0.10, 1.25),
    'claude-opus-5-5': (4.00, 20.00, 0.20, 5.00),
}
WEB_SEARCH_USD = 10.00 / 1000   # per search; web fetch has no per-call fee


def _price(model):
    for name, price in PRICES.items():
        if model == name or model.startswith(name + '-'):
            return price
    return PRICES['claude-sonnet-5']


def _write(record):
    try:
        with open(USAGE_LOG, 'a') as f:
            f.write(json.dumps(record, separators=(',', ':')) + '\n')
    except Exception:
        pass


def _record(purpose, kwargs, response, error, started):
    record = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'app': 'partsbin',
        'event': 'anthropic_call',
        'purpose': purpose,
        'model': kwargs.get('model', ''),
        'duration_ms': int((time.monotonic() - started) * 1000),
        'tools': ','.join(t.get('name', '') for t in kwargs.get('tools') or [] if isinstance(t, dict)),
    }
    if error is not None:
        record.update(ok=False, error=type(error).__name__, error_msg=str(error)[:200])
        return record

    usage = response.usage
    inp = usage.input_tokens or 0
    out = usage.output_tokens or 0
    cache_read = getattr(usage, 'cache_read_input_tokens', None) or 0
    cache_write = getattr(usage, 'cache_creation_input_tokens', None) or 0
    stu = getattr(usage, 'server_tool_use', None)
    searches = (getattr(stu, 'web_search_requests', None) or 0) if stu else 0
    fetches = (getattr(stu, 'web_fetch_requests', None) or 0) if stu else 0

    p_in, p_out, p_read, p_write = _price(record['model'])
    cost = (inp * p_in + out * p_out + cache_read * p_read + cache_write * p_write) / 1e6
    cost += searches * WEB_SEARCH_USD

    record.update(
        ok=True,
        model=getattr(response, 'model', record['model']),
        stop_reason=getattr(response, 'stop_reason', None),
        input_tokens=inp,
        output_tokens=out,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        web_search_requests=searches,
        web_fetch_requests=fetches,
        est_cost_usd=round(cost, 5),
    )
    return record


class _Messages:
    def __init__(self, messages, purpose):
        self._messages = messages
        self._purpose = purpose

    def create(self, **kwargs):
        started = time.monotonic()
        try:
            response = self._messages.create(**kwargs)
        except Exception as e:
            try:
                _write(_record(self._purpose, kwargs, None, e, started))
            except Exception:
                pass
            raise
        try:
            _write(_record(self._purpose, kwargs, response, None, started))
        except Exception:
            pass
        return response

    def __getattr__(self, name):
        return getattr(self._messages, name)


class _Beta:
    def __init__(self, beta, purpose):
        self._beta = beta
        self.messages = _Messages(beta.messages, purpose)

    def __getattr__(self, name):
        return getattr(self._beta, name)


class TrackedClient:
    """Drop-in for anthropic.Anthropic that logs usage of messages.create."""

    def __init__(self, client, purpose):
        self._client = client
        self.messages = _Messages(client.messages, purpose)
        self.beta = _Beta(client.beta, purpose)

    def __getattr__(self, name):
        return getattr(self._client, name)
