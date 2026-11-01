"""BUG-067: block physical input while the agent works, unlock it for the human.

The Easy Apply automation clicks and types through CDP, while a human using the
same window can steal a click, change focus, or close the page. A per-page
:class:`InteractionLock` makes the renderer ignore **physical** input (CDP
``Input.setIgnoreInputEvents``), while browser-use's own ``Input`` commands are
wrapped to open the lock for exactly one command.

Human turns are the exception: Task 3.1 (resume upload), Task 5 (answer banners)
and Task 8 (submit wait) call :func:`begin_human_turn` /
:func:`end_human_turn`. The page must stay unlocked for the whole turn — even if
a watch tick or the tail of an automation command was already in flight when the
turn began (BUG-083).
"""

from __future__ import annotations

import asyncio
import contextlib

# CDP input commands browser-use uses to click/type/scroll. The interaction lock
# wraps these so its own automation still works while physical user input is
# ignored (BUG-067).
_INPUT_METHODS = (
    "dispatchMouseEvent",
    "dispatchKeyEvent",
    "dispatchTouchEvent",
    "insertText",
    "imeSetComposition",
    "synthesizeScrollGesture",
    "synthesizeTapGesture",
)

# One lock per live page; keyed by ``id(page)``, removed on release.
_INTERACTION_LOCKS: dict[int, InteractionLock] = {}


class InteractionLock:
    """Block physical input while the agent works (CDP automation still runs)."""

    def __init__(self, page) -> None:
        self.page = page
        self._client = getattr(page, "_client", None)
        self._session_id = ""
        self._locked = False
        self._human_depth = 0
        self._in_input = 0
        self._originals: dict[str, object] = {}
        self._task: asyncio.Task | None = None
        self._released = False
        # Serializes the CDP ``setIgnoreInputEvents`` writes. Without it a watch
        # tick that inspected the page *before* a human turn began could send its
        # ``ignore=true`` after the turn's ``ignore=false`` (BUG-083).
        self._ignore_lock = asyncio.Lock()

    async def install(self) -> None:
        if self._task is not None or self._released:
            return
        session_id = getattr(self.page, "session_id", "")
        if hasattr(session_id, "__await__"):
            session_id = await session_id
        self._session_id = str(session_id or "")
        self._wrap_input()
        self._task = asyncio.create_task(self._watch())
        await self._apply(True)

    def _input_client(self):
        return getattr(getattr(self._client, "send", None), "Input", None)

    def _wrap_input(self) -> None:
        input_client = self._input_client()
        if input_client is None:
            return
        for name in _INPUT_METHODS:
            original = getattr(input_client, name, None)
            if not callable(original):
                continue
            self._originals[name] = original

            async def wrapper(*args, _orig=original, **kwargs):
                if not self._locked or self._human_depth:
                    return await _orig(*args, **kwargs)
                session_id = kwargs.get("session_id") or self._session_id
                self._in_input += 1
                try:
                    async with self._ignore_lock:
                        # A human turn can start while this command waits: the
                        # page is already unlocked, so only write when it is not.
                        if not self._human_depth:
                            await self._set_ignore(False, session_id)
                    return await _orig(*args, **kwargs)
                finally:
                    self._in_input -= 1
                    # ``_apply`` re-checks the human depth, so the tail of this
                    # command can never re-lock the page under a human's hands.
                    await self._apply(True)

            setattr(input_client, name, wrapper)

    async def _set_ignore(self, ignore: bool, session_id: str | None = None) -> None:
        input_client = self._input_client()
        if input_client is None:
            return
        session_id = session_id or await self._page_session_id()
        with contextlib.suppress(Exception):
            await input_client.setIgnoreInputEvents(
                {"ignore": bool(ignore)}, session_id=session_id or None
            )

    async def _page_session_id(self) -> str:
        """Resolve the page's CDP session id lazily (install may still be running)."""
        if not self._session_id:
            session_id = getattr(self.page, "session_id", "")
            if hasattr(session_id, "__await__"):
                session_id = await session_id
            self._session_id = str(session_id or "")
        return self._session_id

    async def _apply(self, locked: bool) -> None:
        """Write the lock state, serialized and always yielding to a human turn."""
        if self._released:
            return
        async with self._ignore_lock:
            if self._released:
                return
            # A human turn always wins: a watch tick or the tail of an automation
            # command must never re-lock the page while the human owns it (BUG-083).
            locked = bool(locked) and self._human_depth == 0
            self._locked = locked
            await self._set_ignore(locked)

    async def set_human(self, human: bool) -> None:
        """Open/close a human-turn section (nested calls are balanced)."""
        if self._released:
            return
        self._human_depth = max(0, self._human_depth + (1 if human else -1))
        await self._apply(self._human_depth == 0)

    async def _watch(self) -> None:
        while not self._released:
            try:
                await asyncio.sleep(0.6)
                await self._refresh()
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001 - the lock must never crash the run
                continue

    async def _refresh(self) -> None:
        """One watch tick: lock unless this is a login page or a human turn."""
        if self._in_input or self._human_depth:
            return
        on_login = await self._on_login_page()
        # The page probe awaits CDP; a human turn may have started meanwhile.
        if self._in_input or self._human_depth:
            return
        await self._apply(not on_login)

    async def _on_login_page(self) -> bool:
        try:
            url = str(await self.page.get_url() or "").lower()
        except Exception:  # noqa: BLE001 - a dead page is not a login page
            url = ""
        if any(part in url for part in ("/login", "/checkpoint", "/authwall", "/uas/")):
            return True
        try:
            result = await self.page.evaluate(
                "() => !!(document.querySelector('input[type=password], "
                "input[name=\"session_key\"], form.login__form'))"
            )
            return str(result).strip().lower() in ("true", "1")
        except Exception:  # noqa: BLE001 - evaluation is best effort
            return False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._human_depth = 0
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        await self._set_ignore(False)
        input_client = self._input_client()
        if input_client is not None:
            for name, original in self._originals.items():
                setattr(input_client, name, original)
        self._originals.clear()


async def ensure_interaction_lock(page) -> InteractionLock | None:
    key = id(page)
    existing = _INTERACTION_LOCKS.get(key)
    if existing is not None:
        return existing
    if getattr(page, "_client", None) is None:
        return None
    lock = InteractionLock(page)
    _INTERACTION_LOCKS[key] = lock
    try:
        await lock.install()
    except Exception:  # noqa: BLE001 - the lock is best effort, never blocking
        _INTERACTION_LOCKS.pop(key, None)
        with contextlib.suppress(Exception):
            await lock.release()
        return None
    return lock


async def begin_human_turn(page) -> None:
    lock = _INTERACTION_LOCKS.get(id(page)) or await ensure_interaction_lock(page)
    if lock is not None:
        await lock.set_human(True)


async def end_human_turn(page) -> None:
    lock = _INTERACTION_LOCKS.get(id(page))
    if lock is not None:
        await lock.set_human(False)


async def release_interaction_lock(page) -> None:
    lock = _INTERACTION_LOCKS.pop(id(page), None)
    if lock is not None:
        await lock.release()


async def release_all_interaction_locks() -> None:
    for lock in list(_INTERACTION_LOCKS.values()):
        with contextlib.suppress(Exception):
            await lock.release()
    _INTERACTION_LOCKS.clear()
