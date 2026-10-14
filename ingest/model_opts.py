"""Model-specific request options for the extraction / classification calls.

The parser, summarizer and engagement classifier want a plain, deterministic answer with no
extended thinking. Current-generation models have thinking on by default and reject the old
ways of turning it off, so the kwargs differ by model family:

  claude-sonnet-4-6 (and older)   nothing extra (thinking is off unless requested)
  claude-sonnet-5-5               thinking={"type": "between_tools"}  (the documented off switch)
  claude-haiku-5-5                thinking={"type": "disabled"}        (allowed at effort high or below)
  claude-opus-5-5                 cannot be turned off; use effort low

Models are chosen by environment variable so a switch is a Railway change, not a deploy:
  CLAUDE_MODEL           the extraction parser (default claude-sonnet-4-6)
  CLAUDE_MODEL_CLASSIFY  the cheap calls: engagement classifier, deal summaries (default = CLAUDE_MODEL)
"""
import os

DEFAULT_MODEL = "claude-sonnet-4-6"


def parser_model(model=None):
    return model or os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)


def classify_model(model=None):
    return model or os.environ.get("CLAUDE_MODEL_CLASSIFY") or os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)


def gen_kwargs(model):
    m = (model or "").lower()
    if m.startswith("claude-sonnet-5-5"):
        return {"thinking": {"type": "between_tools"}}
    if m.startswith("claude-haiku-5"):
        return {"thinking": {"type": "disabled"}}
    if m.startswith("claude-opus-5"):
        return {"output_config": {"effort": "low"}}
    return {}
