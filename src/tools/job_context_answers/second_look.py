"""One focused re-read of the current job and selected resume."""

import asyncio

from src.tools.token_usage.runtime import tracked_completion


async def reread_context(client, settings, messages):
    messages[0]["content"] += (
        "\nThe first attempt did not produce a grounded answer. Independently re-read "
        "the current sources. Look for overlooked responsibilities, equivalent wording "
        "and relevant resume experience. Use verbatim evidence for every cited source. "
        "If the evidence is insufficient, leave the answer empty."
    )
    async with asyncio.timeout(settings.timeout_seconds):
        return await tracked_completion(
            client.with_options(max_retries=0), model=settings.model, messages=messages,
            temperature=settings.temperature,
        )
