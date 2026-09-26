"""The scripted endpoint refuses a step whose placeholder would fill empty, loudly.

A pin change once moved the sentence stating the session's directory to another
message; the endpoint filled ``{cwd}`` with nothing and every scripted session
failed its reading, which looked like the orchestrator's fault. Now such a step
is never sent: the endpoint records the failure and answers with an error.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from scripted_endpoint import EmptySubstitutionError, Script, serving, text, tool

pytestmark = pytest.mark.integration

NO_DIRECTORY = [{"role": "user", "content": "hello, with no directory stated"}]
STATED = [{"role": "user", "content": "Primary working directory: /tmp/runs/s1-abc"}]


def _post(url: str, messages: list[dict[str, str]]) -> tuple[int, str]:
    body = json.dumps(
        {"model": "claude-sonnet-5", "messages": messages, "tools": [{"name": "Read"}]}
    ).encode()
    request = urllib.request.Request(f"{url}/v1/messages", data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, answer.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


@pytest.mark.parametrize("placeholder", ["{cwd}", "{cwd_name}", "{cwd_ident}"])
def test_a_placeholder_with_no_value_is_refused_and_never_sent(placeholder: str) -> None:
    step = tool("Read", file_path=f"{placeholder}/spec.md")
    with serving(Script(main=[step, text("done")])) as (api, url):
        status, answer = _post(url, NO_DIRECTORY)
    assert status == 500 and "would be filled with nothing" in answer
    assert len(api.failures) == 1 and placeholder in api.failures[0]
    assert api.requests == []  # nothing was served


def test_a_stated_directory_fills_every_placeholder() -> None:
    step = tool("Read", file_path="{cwd}/{cwd_name}/{cwd_ident}.md")
    with serving(Script(main=[step, text("done")])) as (api, url):
        status, answer = _post(url, STATED)
    assert status == 200 and api.failures == []
    assert "/tmp/runs/s1-abc/s1-abc/s1_abc.md" in answer


def test_the_refusal_is_an_exception_for_a_direct_caller() -> None:
    from scripted_endpoint import _fill

    with pytest.raises(EmptySubstitutionError, match=r"\{cwd\}"):
        _fill(tool("Read", file_path="{cwd}/x"), "")
    assert _fill(text("no placeholder"), "") == text("no placeholder")
