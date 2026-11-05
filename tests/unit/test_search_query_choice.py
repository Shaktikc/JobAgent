from io import StringIO
from unittest.mock import Mock

import pytest

from src.search_query_choice import choose_search_query
from src.state import DEFAULT_SEARCH_QUERY


@pytest.mark.parametrize('value, expected', [
    ('  C++\t developer ', 'C++ developer'),
    ('data & analytics', 'data & analytics'),
    ('', DEFAULT_SEARCH_QUERY), (' \n ', DEFAULT_SEARCH_QUERY),
])
def test_explicit_query_skips_question(value, expected):
    ask = Mock(side_effect=AssertionError('unexpected prompt'))
    assert choose_search_query(value, interactive=True, input_func=ask) == expected


@pytest.mark.parametrize('answer, expected', [
    (' Data\t Engineer  ', 'Data Engineer'), ('', DEFAULT_SEARCH_QUERY),
    (' \n ', DEFAULT_SEARCH_QUERY),
])
def test_interactive_answer(answer, expected):
    ask = Mock(return_value=answer)
    assert choose_search_query(interactive=True, input_func=ask) == expected
    assert DEFAULT_SEARCH_QUERY in ask.call_args.args[0]
    assert ask.call_count == 1


@pytest.mark.parametrize('error', [EOFError, KeyboardInterrupt])
def test_interrupted_prompt_defaults(error):
    assert choose_search_query(
        interactive=True, input_func=Mock(side_effect=error), stream=StringIO()
    ) == DEFAULT_SEARCH_QUERY


def test_noninteractive_is_silent():
    output = StringIO()
    assert choose_search_query(interactive=False, stream=output) == DEFAULT_SEARCH_QUERY
    assert output.getvalue() == ''


def test_invalid_answer_retries_then_defaults():
    ask = Mock(return_value='bad\x00query')
    output = StringIO()
    assert choose_search_query(
        interactive=True, input_func=ask, stream=output
    ) == DEFAULT_SEARCH_QUERY
    assert ask.call_count == 3
    assert 'No valid' in output.getvalue()


def test_retry_accepts_valid_answer():
    assert choose_search_query(
        interactive=True, input_func=Mock(side_effect=['\x00', 'SWE'])
    ) == 'SWE'


def test_explicit_invalid_query_raises():
    with pytest.raises(ValueError):
        choose_search_query('bad\x00query')


@pytest.mark.parametrize("flags, answers, expected_prompts", [
    ([], ["Data Engineer", "2", "1"], ["What job", "Choose 1 or 2", "Choose"]),
    (["--query", "Data Engineer"], ["2", "1"], ["Choose 1 or 2", "Choose"]),
    (["--date-range", "week"], ["Data Engineer", "1"], ["What job", "Choose"]),
])
def test_cli_prompt_order(monkeypatch, flags, answers, expected_prompts):
    import src.main as cli
    prompts = []
    replies = iter(answers)
    def ask(prompt):
        prompts.append(prompt)
        return next(replies)
    async def run(args):
        assert args.query == "Data Engineer"
        assert args.date_range == "past_week"
        return {"status": "done", "search_query": args.query}
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", ask)
    monkeypatch.setattr(cli, "_run", run)
    assert cli.main(["--no-dry-run", *flags]) == 0
    assert len(prompts) == len(expected_prompts)
    for prompt, prefix in zip(prompts, expected_prompts, strict=True):
        assert prompt.startswith(prefix)


@pytest.mark.parametrize("flag", ["--clean-profile", "--describe-new-resumes"])
def test_maintenance_never_asks(monkeypatch, flag):
    import src.main as cli
    async def describe(args):
        return 0
    monkeypatch.setattr(cli, "_clean_profile", lambda: 0)
    monkeypatch.setattr(cli, "_describe_new_resumes", describe)
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("prompt")))
    assert cli.main([flag]) == 0


def test_dry_run_query_and_summary(monkeypatch, capsys):
    import src.main as cli
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("prompt")))
    assert cli.main(["--date-range", "24h", "--submission-mode", "manual"]) == 0
    assert "search      : 'software engineer'" in capsys.readouterr().out


@pytest.mark.parametrize("query", ["C++ developer", "data & analytics", "Data Engineer"])
def test_query_state_ingest_url_and_recovery(query):
    from urllib.parse import parse_qs, urlparse

    from src.nodes.ingest import ingest
    from src.state import new_state
    from src.tools.linkedin import build_jobs_search_url
    from src.tools.self_healing.recovery.reopen import job_target_from_state
    state = new_state(search_query=query)
    state.update(ingest(state))
    assert state["search_query"] == query
    assert query in state["log"][0]
    assert parse_qs(urlparse(build_jobs_search_url(query)).query)["keywords"] == [query]
    assert job_target_from_state(state).search_query == query
