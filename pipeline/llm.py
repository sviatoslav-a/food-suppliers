"""Thin wrapper over the `claude` CLI so the pipeline needs no API key on a dev machine.

Swap `run()` for an Anthropic SDK call in production; prompts and parsing stay the same.
"""

import json
import os
import re
import subprocess
import tempfile


class LLMError(RuntimeError):
    pass


def run(prompt: str, model: str = 'haiku', tools: str = '', timeout: int = 300) -> str:
    """Claude by default; falls back to the Codex CLI when Claude is rate limited
    (or LLM_PROVIDER=codex). Tool-using prompts (web search) need Claude."""
    if os.environ.get('LLM_PROVIDER') == 'codex' and not tools:
        return run_codex(prompt, timeout)
    try:
        return run_claude(prompt, model, tools, timeout)
    except LLMError as e:
        if not tools and ('usage_limit' in str(e) or 'session limit' in str(e) or '429' in str(e)):
            return run_codex(prompt, timeout)
        raise


def run_codex(prompt: str, timeout: int = 300) -> str:
    with tempfile.NamedTemporaryFile('r', suffix='.txt') as out:
        p = subprocess.run(['codex', 'exec', '--skip-git-repo-check', '--sandbox', 'read-only', '-o', out.name, '-'],
                           input=prompt, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise LLMError(p.stderr[-500:])
        return open(out.name).read()


def run_claude(prompt: str, model: str = 'haiku', tools: str = '', timeout: int = 300) -> str:
    cmd = ['claude', '-p', '--model', model, '--output-format', 'json']
    if tools:
        cmd += ['--allowedTools', tools]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0 and not p.stdout.strip().startswith('{'):
        raise LLMError(p.stderr[-500:] or p.stdout[-500:])
    out = json.loads(p.stdout)
    if out.get('is_error'):
        raise LLMError(f"{out.get('api_error') or ''} {str(out.get('result'))[:400]}")
    return out.get('result', '')


def parse_json(text: str):
    """Extracts the first JSON object or array from a model reply (fenced or bare)."""
    m = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    body = m.group(1) if m else text
    start = min([i for i in (body.find('{'), body.find('[')) if i >= 0], default=-1)
    if start < 0:
        raise LLMError(f'no JSON in reply: {text[:200]}')
    end = max(body.rfind('}'), body.rfind(']'))
    return json.loads(body[start:end + 1])
