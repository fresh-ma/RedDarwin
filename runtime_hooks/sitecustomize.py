"""Runtime hooks automatically loaded by Python experiment subprocesses."""

from openrouter_routing import (
    install_openai_provider_routing,
    install_raw_http_provider_routing,
)


install_openai_provider_routing()
install_raw_http_provider_routing()

# Only the parallel demo enables the single-target-call transport adapter.
import os
if os.environ.get("REDDARWIN_AUTO_CONFIG"):
    try:
        from scripts.lib.auto_redteaming_runtime import install
        install()
    except Exception as error:
        raise SystemExit("Cannot initialize auto_redteaming runtime: " + type(error).__name__)
