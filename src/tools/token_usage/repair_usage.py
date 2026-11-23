"""Read explicitly reported usage from repair-command JSON lines."""
import json

from . import runtime


def record_repair_usage(output, model):
    count = 0
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        usage = event.get('usage')
        part = event.get('part', {})
        if event.get('type') == 'step_finish' and isinstance(part, dict):
            tokens = part.get('tokens')
            if isinstance(tokens, dict):
                cache = tokens.get('cache', {})
                cached = cache.get('read', 0)
                incoming = tokens.get('input', 0) + cached + cache.get('write', 0)
                outgoing = tokens.get('output', 0) + tokens.get('reasoning', 0)
                usage = {'prompt_tokens': incoming, 'completion_tokens': outgoing,
                         'total_tokens': incoming + outgoing,
                         'prompt_tokens_details': {'cached_tokens': cached}}
        if isinstance(usage, dict) and 'prompt_tokens' in usage:
            runtime.tracker.record(event.get('model') or model, usage)
            count += 1
    runtime.publish()
    return count
