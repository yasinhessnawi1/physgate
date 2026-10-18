"""The credential a real-run driver runs on, by the kind of run it is.

A real run runs on the subscription, at the vendor's own endpoint. A dry run serves every
session from the scripted local endpoint, which is not the vendor's, and a subscription is
refused there before anything is set up. So a dry run runs on a dummy key instead, by the
key's own route to the endpoint, and never reads the env file.
"""

from __future__ import annotations

from collections.abc import Callable

from scripted_endpoint import DUMMY_KEY

from physgate.orchestrator.credentials import Credential


def run_credential(*, dry_run: bool, subscription: Callable[[], str]) -> Credential:
    """A dummy key for a dry run; for a real run, the subscription ``subscription`` reads."""
    if dry_run:
        return Credential("api_key", DUMMY_KEY)
    return Credential("subscription", subscription())
