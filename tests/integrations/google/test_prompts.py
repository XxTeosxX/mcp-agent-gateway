from mcp import types

from app.integrations.google.prompts import (
    DRIVE_PROMPT_REGISTRY,
    DRIVE_PROMPT_REQUIRED_SCOPE,
    DRIVE_PROMPTS,
    render_drive_find_document,
)


def test_prompt_is_registered():
    names = {p.name for p in DRIVE_PROMPTS}
    assert names == {"drive-find-document"}
    assert set(DRIVE_PROMPT_REGISTRY) == {"drive-find-document"}
    assert DRIVE_PROMPT_REQUIRED_SCOPE == "mcp:google:read"


def test_prompt_declares_arguments():
    prompt = next(p for p in DRIVE_PROMPTS if p.name == "drive-find-document")
    args = {a.name: a.required for a in prompt.arguments}
    assert args == {"description": True, "client_name": False}


def test_render_includes_description_and_tool_hint():
    result = render_drive_find_document({"description": "Q3 proposal"})
    assert isinstance(result, types.GetPromptResult)
    text = result.messages[0].content.text
    assert "Q3 proposal" in text
    assert "drive-search-files" in text


def test_render_includes_client_name_when_present():
    result = render_drive_find_document({"description": "contract", "client_name": "Acme"})
    assert "Acme" in result.messages[0].content.text


def test_render_omits_client_hint_when_absent():
    result = render_drive_find_document({"description": "contract"})
    assert "mentions" not in result.messages[0].content.text
