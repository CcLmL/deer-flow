"""Summarization middleware extensions for DeerFlow."""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Any, Protocol, override, runtime_checkable

from langchain.agents import AgentState
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage, get_buffer_string, trim_messages
from langgraph.config import get_config
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

from deerflow.agents.human_input import read_human_input_response
from deerflow.agents.middlewares.dynamic_context_middleware import INJECTED_USER_MESSAGE_ID_SUFFIX, is_dynamic_context_reminder
from deerflow.config.app_config import get_app_config
from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)
_SUMMARY_TRIGGER_MESSAGE_NAME = "summary"
_UNSET = object()
# Valid non-generated summaries for the empty / too-long-to-summarize edges; these
# short-circuit model invocation (and must not be treated as generation failures).
_CANNED_SUMMARIES = frozenset(
    {
        "No previous conversation history.",
        "Previous conversation was too long to summarize.",
    }
)


class SummaryGenerationError(RuntimeError):
    """Summary generation failed after exhausting the run-model fallback.

    Raised only when a caller opts in via ``raise_on_failure`` (the manual
    ``/compact`` path) so a real failure is reported distinctly from "nothing to
    compact". The automatic path leaves ``raise_on_failure`` False and swallows the
    failure, leaving compaction state unchanged for the turn.
    """


@dataclass(frozen=True)
class SummarizationEvent:
    """Context emitted before conversation history is summarized away."""

    messages_to_summarize: tuple[AnyMessage, ...]
    preserved_messages: tuple[AnyMessage, ...]
    thread_id: str | None
    agent_name: str | None
    runtime: Runtime


@dataclass(frozen=True)
class ContextCompactionResult:
    """Result of summarizing old context and retaining the active tail."""

    summary_text: str
    messages_to_summarize: tuple[AnyMessage, ...]
    preserved_messages: tuple[AnyMessage, ...]
    total_tokens: int


@runtime_checkable
class BeforeSummarizationHook(Protocol):
    """Hook invoked before summarization removes messages from state."""

    def __call__(self, event: SummarizationEvent) -> None: ...


def _resolve_thread_id(runtime: Runtime) -> str | None:
    """Resolve the current thread ID from runtime context or LangGraph config."""
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id is None:
        try:
            config_data = get_config()
        except RuntimeError:
            return None
        thread_id = config_data.get("configurable", {}).get("thread_id")
    return thread_id


def _resolve_agent_name(runtime: Runtime) -> str | None:
    """Resolve the current agent name from runtime context or LangGraph config."""
    agent_name = runtime.context.get("agent_name") if runtime.context else None
    if agent_name is None:
        try:
            config_data = get_config()
        except RuntimeError:
            return None
        agent_name = config_data.get("configurable", {}).get("agent_name")
    return agent_name


def _resolve_run_id(runtime: Runtime | None) -> str | None:
    """Resolve the current run ID from runtime context or LangGraph config."""
    run_id = runtime.context.get("run_id") if runtime is not None and runtime.context else None
    if run_id is None:
        try:
            config_data = get_config()
        except RuntimeError:
            return None
        run_id = config_data.get("configurable", {}).get("run_id")
    return run_id


def _is_hidden_user_message(message: HumanMessage) -> bool:
    """Return whether *message* is framework-injected rather than user input.

    ``hide_from_ui`` also marks hidden replies from HumanInputCard, which carry
    a valid structured response and ARE genuine user input — mirror the
    genuine-message test used by input sanitization.
    """
    if message.name == _SUMMARY_TRIGGER_MESSAGE_NAME:
        return True
    return bool(message.additional_kwargs.get("hide_from_ui")) and read_human_input_response(message.additional_kwargs) is None


def _find_current_user_message(messages: list[AnyMessage], current_run_id: str | None) -> HumanMessage | None:
    """Find the user message that started the active run.

    ``ThreadDataMiddleware.before_agent`` stamps the run's incoming HumanMessage
    with ``additional_kwargs["run_id"]``. Matching on that id is the only precise
    way to distinguish the active question from an older ID-swapped ``__user``
    question that must be summarized with the rest of the history.

    When no run id is available (manual compaction, replay), fall back to the
    newest genuine HumanMessage. A run id that is present but does not match any
    message returns ``None``: guessing could resurrect a stale question.
    """
    if current_run_id is not None:
        for message in reversed(messages):
            if isinstance(message, HumanMessage) and not _is_hidden_user_message(message) and message.additional_kwargs.get("run_id") == current_run_id:
                return message
        return None

    for message in reversed(messages):
        if isinstance(message, HumanMessage) and not _is_hidden_user_message(message):
            return message
    return None


class DeerFlowSummarizationMiddleware(SummarizationMiddleware):
    """Summarization middleware with pre-compression hook dispatch."""

    def __init__(
        self,
        *args,
        before_summarization: list[BeforeSummarizationHook] | None = None,
        app_config: Any | None = None,
        configured_model_name: str | None = None,
        run_model_name: str | None = None,
        anchor_model_name: str | None = _UNSET,  # type: ignore[assignment]
        extensions=None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._before_summarization_hooks = before_summarization or []
        # Model-ownership state. The model that actually executes the run is selected
        # per run and is the authoritative source of truth, so the caller (lead /
        # subagent / manual builders) supplies it directly as ``run_model_name``
        # instead of the middleware re-deriving it from ``runtime.context`` /
        # ``get_config()`` — those fields do not carry a custom agent's or a subagent's
        # resolved model.
        #
        # ``configured_model_name`` is the explicitly configured summary model
        # (``None`` => summarize with the run's own model). ``run_model_name`` is the
        # model the run executes with; when they differ and the summary provider is
        # broken (expired key, quota, outage) the run's own working model can still
        # compact.
        self._app_config = app_config
        self._configured_summary_model_name = configured_model_name
        self._run_model_name = run_model_name
        # The summary LLM call runs inside a LangGraph middleware hook, so its token
        # stream would otherwise be captured by the messages-tuple stream callback and
        # broadcast to the frontend as a phantom AI message. Tag a dedicated model copy
        # with TAG_NOSTREAM so the streaming handler skips it.
        # Keep self.model untagged so the parent's profile / ls_params inspection still works.
        self._summary_model = self._tag_nostream(self.model)
        # ``self.model`` is the pre-built *anchor* model: it drives the parent's token
        # counter / profile inspection and is reused verbatim by generation when a
        # candidate matches its name. The factory builds it guarded and passes its name
        # explicitly; direct construction (tests) mirrors the old factory choice
        # (configured model, else default) so the passed ``model`` is the primary.
        if anchor_model_name is _UNSET:
            self._anchor_model_name = configured_model_name or self._default_model_name()
        else:
            self._anchor_model_name = anchor_model_name
        if extensions is None:
            from deerflow.extensions import get_agent_build_extensions

            extensions = get_agent_build_extensions()
        self._extensions = extensions
        # Nostream generation models built lazily by name and cached (None = a build
        # that failed, so a broken candidate config is not retried every turn and does
        # not escape the fail-open boundary).
        self._model_cache: dict[str | None, Any] = {}

    def _tag_nostream(self, model: Any) -> Any:
        """Return a copy of ``model`` carrying TAG_NOSTREAM without clobbering tags.

        lead_agent/agent.py binds "middleware:summarize" for RunJournal attribution;
        RunnableBinding.with_config shallow-merges config, so existing tags must be
        preserved explicitly instead of being overwritten with just [TAG_NOSTREAM].
        """
        existing_tags = list((getattr(model, "config", None) or {}).get("tags") or [])
        merged_tags = [*existing_tags, TAG_NOSTREAM] if TAG_NOSTREAM not in existing_tags else existing_tags
        return model.with_config(tags=merged_tags)

    def _default_model_name(self) -> str | None:
        if self._app_config is None:
            return None
        models = getattr(self._app_config, "models", None)
        return models[0].name if models else None

    def _generation_candidate_names(self) -> list[str | None]:
        """Ordered summary-generation candidates by name (deduplicated).

        Explicit summary model: the configured model first, then the run's own model
        as a distinct fallback. ``model_name: null``: the run's own model only — its
        construction is the primary, so there is no eager dependency on
        ``config.models[0]`` (a bare default is used only when no run model was
        resolved). A ``None`` entry means "let ``create_chat_model`` pick the default",
        which only occurs when nothing resolves a name.
        """
        default = self._default_model_name()
        if self._configured_summary_model_name is not None:
            names = [self._configured_summary_model_name, self._run_model_name or default]
        else:
            names = [self._run_model_name or default]
        deduped: list[str | None] = []
        seen: set[str | None] = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            deduped.append(name)
        return deduped

    def _model_for(self, name: str | None) -> Any | None:
        """The nostream summary model for ``name``, built lazily and guarded.

        Returns the pre-built anchor when ``name`` matches it (no rebuild), otherwise
        constructs and caches. A construction failure is caught and cached as ``None``
        so a broken candidate config never escapes the fail-open boundary, is never
        retried this turn, and still lets the next candidate run.
        """
        if name == self._anchor_model_name:
            return self._summary_model
        if name in self._model_cache:
            return self._model_cache[name]
        try:
            model = create_chat_model(
                name=name,
                thinking_enabled=False,
                app_config=self._app_config,
                attach_tracing=False,
            )
            built = self._tag_nostream(model.with_config(tags=["middleware:summarize"]))
        except Exception:
            logger.exception("Failed to build summary model %r; trying the next candidate", name)
            built = None
        self._model_cache[name] = built
        return built

    @override
    def _create_summary(self, messages_to_summarize: list[AnyMessage]) -> str | None:
        return self._summarize_with(messages_to_summarize)

    @override
    async def _acreate_summary(self, messages_to_summarize: list[AnyMessage]) -> str | None:
        return await self._asummarize_with(messages_to_summarize)

    def _prepare_summary_prompt(self, messages_to_summarize: list[AnyMessage], previous_summary: str | None) -> str | None:
        """Return the formatted prompt, or a canned string for the empty/too-long edges.

        A non-``None`` return that is not a real prompt (the two canned strings) is a
        valid summary and short-circuits generation; ``None`` means "build a prompt".
        """
        if not messages_to_summarize:
            return "No previous conversation history."
        prompt = self._build_summary_prompt(messages_to_summarize, previous_summary=previous_summary)
        if prompt is None:
            return "Previous conversation was too long to summarize."
        return prompt

    @staticmethod
    def _nonempty_summary(text: Any) -> str | None:
        """Normalize a model response's text; a blank/whitespace-only body is a failure.

        Committing ``""`` as a summary would fire the before_summarization hooks and
        remove all prior history for an empty replacement, so an empty body is treated
        as generation failure (try the fallback, or leave state unchanged) rather than
        a valid summary.
        """
        stripped = text.strip() if isinstance(text, str) else ""
        return stripped or None

    def _summarize_with(self, messages_to_summarize: list[AnyMessage], previous_summary: str | None = None) -> str | None:
        """Mirror the parent ``_create_summary`` but invoke the nostream-tagged model.

        We do not swap ``self.model`` at the instance level: the agent/middleware is
        cached and reused across concurrent runs, so a temporary swap would leak the
        ``RunnableBinding`` to other coroutines during ``await`` and break parent logic
        that inspects the raw model (``profile`` / ``_get_ls_params``).

        Generation uses the run's own model (``model_name: null``) or the explicitly
        configured summary model, falling back to the run model on failure so a broken
        summary provider cannot disable compaction while a working model is available.
        """
        prompt = self._prepare_summary_prompt(messages_to_summarize, previous_summary)
        if prompt is None or prompt in _CANNED_SUMMARIES:
            return prompt
        # Walk the ordered candidates; each attempt owns its full lifecycle (lazy
        # guarded construction -> invoke -> text extraction -> non-empty validation),
        # and any failure at any stage falls through to the next candidate. When all
        # candidates fail the caller leaves compaction state unchanged.
        names = self._generation_candidate_names()
        for index, name in enumerate(names):
            text = self._invoke_summary(self._model_for(name), prompt, last=index == len(names) - 1)
            if text is not None:
                return text
        return None

    async def _asummarize_with(
        self,
        messages_to_summarize: list[AnyMessage],
        previous_summary: str | None = None,
        *,
        task_store=None,
    ) -> str | None:
        """Async counterpart of :meth:`_summarize_with` using the nostream model."""
        prompt = self._prepare_summary_prompt(messages_to_summarize, previous_summary)
        if prompt is None or prompt in _CANNED_SUMMARIES:
            return prompt
        names = self._generation_candidate_names()
        for index, name in enumerate(names):
            text = await self._ainvoke_summary(
                self._model_for(name),
                prompt,
                last=index == len(names) - 1,
                model_name=name,
                task_store=task_store,
            )
            if text is not None:
                return text
        return None

    def _invoke_summary(self, model: Any | None, prompt: str, *, last: bool = False) -> str | None:
        """Invoke ``model`` for a summary; ``None`` on error or a blank response.

        Text extraction / non-empty validation runs *inside* the try: reading the
        response's ``.text`` is part of consuming the provider result, so a failing
        accessor must convert to a candidate failure (fall through) rather than escape
        the fail-open boundary.

        Deliberately unobserved by system-model-call extensions, unlike
        :meth:`_ainvoke_summary`. Both this method and its only host caller
        (``compact_state``) are the sync half of an async-only runtime: the agent runs
        through ``abefore_model``, and ``runtime/context_compaction.py`` calls
        ``acompact_state``. Notifying from here would have to block the calling thread
        on the extension loop for a call site the host never reaches.
        """
        if model is None:
            return None
        try:
            response = model.invoke(prompt, config={"metadata": {"lc_source": "summarization"}})
            return self._checked_summary(response, last)
        except Exception:
            self._log_summary_error(last)
            return None

    async def _ainvoke_summary(
        self,
        model: Any | None,
        prompt: str,
        *,
        last: bool = False,
        model_name: str | None = None,
        task_store=None,
    ) -> str | None:
        """Async counterpart of :meth:`_invoke_summary`."""
        if model is None:
            return None
        try:
            invoke_config = {"metadata": {"lc_source": "summarization"}}
            extensions = getattr(self, "_extensions", None)
            if extensions is None:
                response = await model.ainvoke(prompt, config=invoke_config)
            else:
                from deerflow_extension_api import SystemOperationKind

                from deerflow.extensions.notify import observe_system_model_call

                response = await observe_system_model_call(
                    extensions,
                    SystemOperationKind.SUMMARIZATION,
                    messages=prompt,
                    model_name=model_name,
                    invoke_config=invoke_config,
                    invoke=lambda: model.ainvoke(prompt, config=invoke_config),
                    task_store=task_store,
                )
            return self._checked_summary(response, last)
        except Exception:
            self._log_summary_error(last)
            return None

    def _checked_summary(self, response: Any, last: bool) -> str | None:
        summary = self._nonempty_summary(getattr(response, "text", None))
        if summary is None:
            self._log_summary_empty(last)
        return summary

    @staticmethod
    def _log_summary_error(last: bool) -> None:
        if last:
            logger.exception("Summary generation failed; skipping compaction this turn")
        else:
            logger.warning("Summary generation failed; falling back to the run model", exc_info=True)

    @staticmethod
    def _log_summary_empty(last: bool) -> None:
        if last:
            logger.warning("Summary model returned empty text; skipping compaction this turn")
        else:
            logger.warning("Summary model returned empty text; falling back to the run model")

    @staticmethod
    def _summary_count_message(summary_text: str) -> HumanMessage:
        return HumanMessage(content=summary_text, name=_SUMMARY_TRIGGER_MESSAGE_NAME)

    def _messages_for_trigger_count(self, messages: list[AnyMessage], summary_text: str | None) -> list[AnyMessage]:
        if not summary_text:
            return messages
        return [*messages, self._summary_count_message(summary_text)]

    @staticmethod
    def _bound_text(text: str, cap: int) -> str:
        if len(text) <= cap:
            return text
        if cap <= 0:
            return ""
        head = cap * 2 // 3
        omitted_marker = "\n...\n"
        if cap <= len(omitted_marker):
            return text[:cap]
        tail = max(0, cap - head - len(omitted_marker))
        if tail == 0:
            return text[:cap]
        return f"{text[:head]}{omitted_marker}{text[-tail:]}"

    def _trim_summary_section_text(self, text: str, max_tokens: int, *, strategy: str) -> str:
        if not text.strip():
            return ""
        max_tokens = max(1, max_tokens)
        try:
            trimmed = trim_messages(
                [HumanMessage(content=text)],
                max_tokens=max_tokens,
                token_counter=self.token_counter,
                strategy=strategy,
                allow_partial=True,
                text_splitter=list,
            )
            if trimmed:
                content = trimmed[-1].content
                if isinstance(content, str) and content.strip():
                    return content
        except Exception:
            logger.debug("Failed to trim summary prompt section with token counter; falling back to deterministic text cap", exc_info=True)
        return self._bound_text(text, max_tokens)

    def _build_summary_input_text(self, formatted_messages: str, previous_summary: str | None = None) -> str | None:
        if self.trim_tokens_to_summarize is None:
            trimmed_new_messages = formatted_messages
            trimmed_previous_summary = previous_summary.strip() if previous_summary else ""
        else:
            max_tokens = max(1, self.trim_tokens_to_summarize)
            if previous_summary:
                new_message_tokens = max(1, max_tokens // 2)
                previous_summary_tokens = max(1, max_tokens - new_message_tokens)
                trimmed_previous_summary = self._trim_summary_section_text(
                    previous_summary.strip(),
                    previous_summary_tokens,
                    strategy="last",
                )
                trimmed_new_messages = self._trim_summary_section_text(
                    formatted_messages,
                    new_message_tokens,
                    strategy="first",
                )
            else:
                trimmed_previous_summary = ""
                trimmed_new_messages = self._trim_summary_section_text(
                    formatted_messages,
                    max_tokens,
                    strategy="first",
                )

        # Escape < > & before embedding into the <existing_summary>/<new_messages>
        # blocks. new_messages is get_buffer_string over the raw state["messages"]
        # tail (InputSanitizationMiddleware only overrides the ModelRequest, never
        # state, so the summarizer sees genuine user text); existing_summary is the
        # prior turn's summary_text. An unescaped value like "</new_messages>..."
        # would close the block and forge an authority section for the extraction
        # LLM. Same block-breakout defense #4162 applied to the <conversation> block
        # and #4097 to the <memory> block. Escape after trimming so a trailing "..."
        # cannot split an entity; quote=False because content lands in element-text
        # position (never an attribute value).
        parts: list[str] = []
        if trimmed_previous_summary:
            parts.extend(
                [
                    "<existing_summary>",
                    html.escape(trimmed_previous_summary, quote=False),
                    "</existing_summary>",
                    "",
                ]
            )
        if trimmed_new_messages:
            parts.extend(
                [
                    "<new_messages>",
                    html.escape(trimmed_new_messages, quote=False),
                    "</new_messages>",
                ]
            )
        if not parts:
            return None
        return "\n".join(parts)

    def _build_summary_prompt(self, messages_to_summarize: list[AnyMessage], previous_summary: str | None = None) -> str | None:
        """Build the summary prompt, returning ``None`` when trimming leaves nothing."""
        trimmed_messages = self._trim_messages_for_summary(messages_to_summarize)
        if not trimmed_messages:
            trimmed_messages = messages_to_summarize[-1:]
        if not trimmed_messages:
            return None
        # Format messages to avoid token inflation from metadata when str() is called on
        # message objects.
        formatted_messages = get_buffer_string(trimmed_messages)
        formatted_messages = self._build_summary_input_text(formatted_messages, previous_summary=previous_summary)
        if not formatted_messages:
            return None
        return self.summary_prompt.format(messages=formatted_messages).rstrip()

    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._maybe_summarize(state, runtime)

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return await self._amaybe_summarize(state, runtime)

    def _prepare_compaction(
        self,
        state: AgentState,
        runtime: Runtime,
        *,
        force: bool = False,
    ) -> tuple[list[AnyMessage], list[AnyMessage], str | None, int] | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)

        previous_summary = state.get("summary_text") if isinstance(state.get("summary_text"), str) else None
        trigger_messages = self._messages_for_trigger_count(messages, previous_summary)
        total_tokens = self.token_counter(trigger_messages)
        if not force and not self._should_summarize(trigger_messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index(messages)
        if cutoff_index <= 0:
            return None

        current_user_message = _find_current_user_message(messages, _resolve_run_id(runtime))
        messages_to_summarize, preserved_messages = self._partition_messages(messages, cutoff_index)
        messages_to_summarize, preserved_messages = self._preserve_active_context(messages_to_summarize, preserved_messages, current_user_message)
        if not messages_to_summarize:
            return None
        return messages_to_summarize, preserved_messages, previous_summary, total_tokens

    def compact_state(
        self,
        state: AgentState,
        runtime: Runtime,
        *,
        force: bool = False,
        raise_on_failure: bool = False,
    ) -> ContextCompactionResult | None:
        """Summarize old context and retain the active tail.

        ``force`` bypasses the automatic trigger threshold (a manual caller always
        wants to compact). ``raise_on_failure`` is a *separate* concern: when set (the
        manual ``/compact`` path), a generation failure raises ``SummaryGenerationError``
        so it can be reported distinctly from "nothing to compact"; the automatic path
        leaves it False and swallows the failure, retrying on a later triggered turn.
        """
        prepared = self._prepare_compaction(state, runtime, force=force)
        if prepared is None:
            return None
        messages_to_summarize, preserved_messages, previous_summary, total_tokens = prepared
        summary = self._summarize_with(messages_to_summarize, previous_summary=previous_summary)
        if summary is None:
            if raise_on_failure:
                raise SummaryGenerationError("summary generation failed")
            return None
        # Fire hooks only once a replacement summary exists — flushing pre-compaction
        # messages into durable memory for a summary that never materializes would
        # duplicate that work on the next attempt. Messages are still removed after
        # this returns (in _maybe_summarize), so hooks run before they are gone.
        self._fire_hooks(messages_to_summarize, preserved_messages, runtime)
        return ContextCompactionResult(
            summary_text=summary,
            messages_to_summarize=tuple(messages_to_summarize),
            preserved_messages=tuple(preserved_messages),
            total_tokens=total_tokens,
        )

    async def acompact_state(
        self,
        state: AgentState,
        runtime: Runtime,
        *,
        force: bool = False,
        raise_on_failure: bool = False,
    ) -> ContextCompactionResult | None:
        """Async counterpart of :meth:`compact_state` (see it for ``raise_on_failure``)."""
        prepared = self._prepare_compaction(state, runtime, force=force)
        if prepared is None:
            return None
        messages_to_summarize, preserved_messages, previous_summary, total_tokens = prepared
        from deerflow_extension_api import task_store_from_runtime

        summary = await self._asummarize_with(
            messages_to_summarize,
            previous_summary=previous_summary,
            task_store=task_store_from_runtime(runtime),
        )
        if summary is None:
            if raise_on_failure:
                raise SummaryGenerationError("summary generation failed")
            return None
        # Fire hooks only once a replacement summary exists (see compact_state).
        self._fire_hooks(messages_to_summarize, preserved_messages, runtime)
        return ContextCompactionResult(
            summary_text=summary,
            messages_to_summarize=tuple(messages_to_summarize),
            preserved_messages=tuple(preserved_messages),
            total_tokens=total_tokens,
        )

    def _maybe_summarize(self, state: AgentState, runtime: Runtime) -> dict | None:
        result = self.compact_state(state, runtime, force=False)
        if result is None:
            return None
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *result.preserved_messages,
            ],
            "summary_text": result.summary_text,
        }

    async def _amaybe_summarize(self, state: AgentState, runtime: Runtime) -> dict | None:
        result = await self.acompact_state(state, runtime, force=False)
        if result is None:
            return None
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *result.preserved_messages,
            ],
            "summary_text": result.summary_text,
        }

    def _preserve_active_context(
        self,
        messages_to_summarize: list[AnyMessage],
        preserved_messages: list[AnyMessage],
        current_user_message: HumanMessage | None,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        """Keep hidden context reminders and the active user turn out of compression.

        Two kinds of messages are rescued:

        * **Tagged dynamic-context reminders** (the date ``SystemMessage`` and the
          optional ``__memory`` HumanMessage). If summarization removed the date
          reminder, DynamicContextMiddleware would lose the already-injected date
          and re-inject one at the wrong point of the conversation.
        * **The current run's user message and its ID-swap peers** (``X``,
          ``X__memory``, ``X__user``). The current question must stay literal in
          the model window; a summary alone is too easy to lose mid-run.

        Historical ``__user`` questions are deliberately **not** rescued. They are
        ordinary conversation content and belong in the summary. The old blanket
        ID-swap peer rescue hoisted every first-turn question to the front of the
        preserved window, so after a long run the model saw a stale question as
        the only literal user request and answered it instead of the active task
        (production: T034 resurrected mid-T042 run). Their date/memory reminders
        are still rescued, because they carry authoritative framework context.
        """
        # Resolve the current turn's ID-swap base. ``removesuffix`` is suffix-only,
        # so a stable id containing "__" in the middle stays intact.
        current_base_ids: set[str] = set()
        if current_user_message is not None and current_user_message.id:
            current_base = current_user_message.id.removesuffix(INJECTED_USER_MESSAGE_ID_SUFFIX)
            if current_base:
                current_base_ids.add(current_base)

        # Single-pass partition preserves chronological order across multiple
        # rescued reminders in one summarization window.
        rescued: list[AnyMessage] = []
        remaining: list[AnyMessage] = []
        for msg in messages_to_summarize:
            is_current_user = current_user_message is not None and (msg is current_user_message or (current_user_message.id is not None and msg.id == current_user_message.id))
            is_current_peer = bool(current_base_ids and msg.id and any(msg.id.startswith(base + "__") or msg.id == base for base in current_base_ids))
            if is_dynamic_context_reminder(msg) or is_current_user or is_current_peer:
                rescued.append(msg)
            else:
                remaining.append(msg)
        return remaining, rescued + preserved_messages

    def _fire_hooks(
        self,
        messages_to_summarize: list[AnyMessage],
        preserved_messages: list[AnyMessage],
        runtime: Runtime,
    ) -> None:
        if not self._before_summarization_hooks:
            return

        event = SummarizationEvent(
            messages_to_summarize=tuple(messages_to_summarize),
            preserved_messages=tuple(preserved_messages),
            thread_id=_resolve_thread_id(runtime),
            agent_name=_resolve_agent_name(runtime),
            runtime=runtime,
        )

        for hook in self._before_summarization_hooks:
            try:
                hook(event)
            except Exception:
                hook_name = getattr(hook, "__name__", None) or type(hook).__name__
                logger.exception("before_summarization hook %s failed", hook_name)


def _build_summary_anchor(candidate_names: list[str | None], app_config: Any) -> tuple[Any | None, str | None]:
    """Build the first constructible model among ``candidate_names`` (guarded).

    The returned model is tagged for RunJournal attribution but *not* TAG_NOSTREAM (the
    middleware wraps a nostream copy). It becomes the parent's token-counter / profile
    anchor and is reused for generation when a candidate matches its name. A per-name
    construction failure is swallowed and the next candidate tried, so a broken primary
    constructor neither breaks agent construction nor skips the healthy run model; a
    trailing ``None`` name asks ``create_chat_model`` for its own default. Returns
    ``(None, None)`` when nothing can be constructed.
    """
    tried: set[str | None] = set()
    for name in candidate_names:
        if name in tried:
            continue
        tried.add(name)
        try:
            model = create_chat_model(name=name, thinking_enabled=False, app_config=app_config, attach_tracing=False)
        except Exception:
            logger.exception("Failed to build summary anchor model %r; trying the next candidate", name)
            continue
        return model.with_config(tags=["middleware:summarize"]), name
    return None, None


def create_summarization_middleware(
    *,
    app_config: Any | None = None,
    keep: tuple[str, int | float] | None = None,
    skip_memory_flush: bool = False,
    run_model_name: str | None = None,
    extensions=None,
) -> DeerFlowSummarizationMiddleware | None:
    """Create the configured summarization middleware.

    Both the lead-agent automatic path and the manual context-compaction path
    use this factory so model resolution, hooks, prompt config, and retention
    defaults cannot drift.

    ``run_model_name`` is the model the run actually executes with, resolved by the
    caller (the lead / subagent / manual builders each already resolve it) and passed
    in as the authoritative source of truth for ``model_name: null`` summarization and
    the explicit-summary-model fallback. The middleware does not re-derive it from
    ``runtime.context`` / ``get_config()``, which do not carry a custom agent's or a
    subagent's resolved model.

    ``skip_memory_flush`` omits the ``memory_flush_hook`` that otherwise
    flushes pre-compaction messages into the durable memory queue. The lead
    chain keeps it (research should persist); the subagent chain sets it so a
    subagent's INTERNAL turns (the "Task" human message + intermediate AI/tool
    turns) are not written into the PARENT thread's durable memory — the hook
    is keyed by ``thread_id`` and subagents share the parent's ``thread_id``
    (#3875 Phase 3 review).
    """
    resolved_app_config = app_config or get_app_config()
    config = resolved_app_config.summarization

    if not config.enabled:
        return None

    trigger = None
    if config.trigger is not None:
        if isinstance(config.trigger, list):
            trigger = [item.to_tuple() for item in config.trigger]
        else:
            trigger = config.trigger.to_tuple()

    default_name = resolved_app_config.models[0].name if getattr(resolved_app_config, "models", None) else None
    # Build the anchor (token-counter / profile model, reused for generation) guarded,
    # rather than eagerly building the configured/default model and letting a broken
    # constructor escape. Candidates in order: the primary generation model (configured
    # summary model, else the run's own model), then the run model, then the default,
    # then ``None`` (create_chat_model's default) as a last resort. So the null case
    # builds from ``run_model_name`` — not ``config.models[0]`` — and a broken primary
    # falls through to the healthy run model instead of failing agent construction.
    primary_name = config.model_name or run_model_name or default_name
    anchor_model, anchor_name = _build_summary_anchor(
        [primary_name, run_model_name or default_name, default_name, None],
        resolved_app_config,
    )
    if anchor_model is None:
        logger.warning("Summarization is enabled but no summary model could be constructed; compaction is unavailable for this build")
        return None

    kwargs: dict[str, Any] = {
        "model": anchor_model,
        "trigger": trigger,
        "keep": keep or config.keep.to_tuple(),
    }
    if config.trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = config.trim_tokens_to_summarize
    if config.summary_prompt is not None:
        kwargs["summary_prompt"] = config.summary_prompt

    hooks: list[BeforeSummarizationHook] = []
    if resolved_app_config.memory.enabled and not skip_memory_flush:
        from deerflow.agents.memory.summarization_hook import memory_flush_hook

        hooks.append(memory_flush_hook)

    return DeerFlowSummarizationMiddleware(
        **kwargs,
        before_summarization=hooks,
        app_config=resolved_app_config,
        configured_model_name=config.model_name,
        run_model_name=run_model_name,
        anchor_model_name=anchor_name,
        extensions=extensions,
    )
