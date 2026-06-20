"""FastAPI service for Jarvis.

The app object lives in jarvis.api.app (referenced by uvicorn as
"jarvis.api.app:app"). We deliberately do not re-export it here, so the
name `jarvis.api.app` always resolves to the *module*, not the instance.
"""
