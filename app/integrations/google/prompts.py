from collections.abc import Callable

from mcp import types

DRIVE_PROMPT_REQUIRED_SCOPE = "mcp:google:read"

DRIVE_PROMPTS: list[types.Prompt] = [
    types.Prompt(
        name="drive-find-document",
        description="Guide the model to find a document in Google Drive using structured filters.",
        arguments=[
            types.PromptArgument(
                name="description",
                description="What to look for (e.g. 'Q3 proposal for Acme')",
                required=True,
            ),
            types.PromptArgument(
                name="client_name",
                description="Optional client/company name to narrow the search",
                required=False,
            ),
        ],
    )
]


def render_drive_find_document(arguments: dict | None) -> types.GetPromptResult:
    arguments = arguments or {}
    description = arguments.get("description", "")
    client_name = arguments.get("client_name")
    hint = f" The document likely mentions '{client_name}'." if client_name else ""
    text = (
        f"Find a document in Google Drive: {description}.{hint}\n\n"
        "Use the `drive-search-files` tool with structured filters "
        "(full_text, name_contains, mime_type, in_folder, modified_after). "
        "Do not write raw Drive query syntax."
    )
    return types.GetPromptResult(
        description="Drive document search guidance",
        messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))],
    )


DRIVE_PROMPT_REGISTRY: dict[str, Callable[[dict | None], types.GetPromptResult]] = {
    "drive-find-document": render_drive_find_document,
}
