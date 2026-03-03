import argparse
import subprocess
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

import karl


def test_ts_contains_message():
    result = karl.ts("hello")
    assert "hello" in result
    assert result.startswith("[")
    assert "]" in result


def test_expand_agents_replaces_placeholder(tmp_path):
    agent_file = tmp_path / "quality.txt"
    agent_file.write_text("check for bugs")

    result = karl.expand_agents("before {{agent:quality}} after", tmp_path)
    assert "--- quality ---" in result
    assert "check for bugs" in result
    assert "--- end ---" in result
    assert "{{agent:quality}}" not in result


def test_expand_agents_missing_file(tmp_path):
    result = karl.expand_agents("{{agent:missing}}", tmp_path)
    assert result == "{{agent:missing}}"


def test_expand_agents_no_placeholders():
    result = karl.expand_agents("no placeholders here", "/tmp")
    assert result == "no placeholders here"


def test_expand_agents_multiple(tmp_path):
    (tmp_path / "a.txt").write_text("agent a")
    (tmp_path / "b.txt").write_text("agent b")

    result = karl.expand_agents("{{agent:a}} and {{agent:b}}", tmp_path)
    assert "agent a" in result
    assert "agent b" in result
    assert "{{agent:" not in result


def test_progress_file_for():
    assert karl.progress_file_for("plan.md") == ".karl/.progress_plan.txt"
    assert karl.progress_file_for("docs/my-feature.md") == ".karl/.progress_my-feature.txt"




def test_build_setup_prompt():
    prompt = karl.build_setup_prompt("/path/to/plan.md")
    assert "/path/to/plan.md" in prompt
    assert "{{PLAN_FILE}}" not in prompt


def test_build_finalize_prompt():
    prompt = karl.build_finalize_prompt("/path/to/plan.md")
    assert "/path/to/plan.md" in prompt
    assert "{{PLAN_FILE}}" not in prompt


def test_build_implementation_prompt():
    prompt = karl.build_implementation_prompt("/path/to/plan.md")
    assert "/path/to/plan.md" in prompt
    assert "{{PLAN_FILE}}" not in prompt
    assert "{{PROGRESS_FILE}}" not in prompt
    assert ".karl/.progress_plan.txt" in prompt


def test_build_review_first_prompt():
    prompt = karl.build_review_first_prompt("plan.md")
    assert "{{agent:" not in prompt
    assert "{{PLAN_FILE}}" not in prompt
    assert "{{PROGRESS_FILE}}" not in prompt
    assert "plan.md" in prompt
    assert ".karl/.progress_plan.txt" in prompt


def test_build_review_second_prompt():
    prompt = karl.build_review_second_prompt("plan.md")
    assert "{{agent:" not in prompt
    assert "{{PLAN_FILE}}" not in prompt
    assert "{{PROGRESS_FILE}}" not in prompt
    assert "plan.md" in prompt
    assert ".karl/.progress_plan.txt" in prompt


def test_build_crossreview_analyze_prompt():
    prompt = karl.build_crossreview_analyze_prompt("plan.md", "gpt-4.1", "some output")
    assert "plan.md" in prompt
    assert "gpt-4.1" in prompt
    assert "some output" in prompt
    assert "{{PLAN_FILE}}" not in prompt
    assert "{{MODEL_NAME}}" not in prompt
    assert "{{REVIEW_CONTEXT}}" not in prompt


def test_build_crossreview_fix_prompt():
    prompt = karl.build_crossreview_fix_prompt("plan.md", "gpt-5-mini", "review text")
    assert "plan.md" in prompt
    assert "gpt-5-mini" in prompt
    assert "review text" in prompt
    assert "{{PLAN_FILE}}" not in prompt
    assert "{{MODEL_NAME}}" not in prompt
    assert "{{REVIEW_CONTEXT}}" not in prompt


def make_mock_proc(stdout_lines, returncode=0):
    proc = MagicMock()
    proc.stdout = iter(stdout_lines)
    proc.wait.return_value = None
    proc.returncode = returncode
    return proc


@patch("karl.subprocess.Popen")
def test_run_copilot_exception_terminates_process(mock_popen):
    proc = MagicMock()

    class RaisingIter:
        def __iter__(self):
            yield "first line\n"
            raise IOError("read error")

    proc.stdout = RaisingIter()
    mock_popen.return_value = proc

    with pytest.raises(IOError):
        karl.run_copilot("do something")
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=10)


@patch("karl.subprocess.Popen")
def test_run_copilot_exception_kills_process_on_wait_timeout(mock_popen):
    proc = MagicMock()

    class RaisingIter:
        def __iter__(self):
            raise IOError("read error")
            yield  # make it a generator

    proc.stdout = RaisingIter()
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="copilot", timeout=10), None]
    mock_popen.return_value = proc

    with pytest.raises(IOError):
        karl.run_copilot("do something")
    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2


@patch("karl.subprocess.Popen")
def test_run_copilot_exception_not_masked_when_kill_wait_raises(mock_popen):
    proc = MagicMock()

    class RaisingIter:
        def __iter__(self):
            raise IOError("read error")
            yield  # make it a generator

    proc.stdout = RaisingIter()
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="copilot", timeout=10),
        OSError("wait failed"),
    ]
    mock_popen.return_value = proc

    with pytest.raises(IOError):
        karl.run_copilot("do something")
    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2


@patch("karl.subprocess.Popen")
def test_run_copilot_success(mock_popen):
    mock_popen.return_value = make_mock_proc(
        ["some output\n", f"{karl.SIGNAL_COMPLETED}\n"],
    )
    result, output = karl.run_copilot("do something", model="gpt-4.1")
    assert result is True
    assert "some output" in output
    assert karl.SIGNAL_COMPLETED in output


@patch("karl.subprocess.Popen")
def test_run_copilot_failure_signal(mock_popen):
    mock_popen.return_value = make_mock_proc(
        [f"{karl.SIGNAL_FAILED}\n"],
    )
    result, output = karl.run_copilot("do something")
    assert result is False


@patch("karl.subprocess.Popen")
def test_run_copilot_nonzero_exit(mock_popen):
    mock_popen.return_value = make_mock_proc(
        [f"{karl.SIGNAL_COMPLETED}\n"],
        returncode=1,
    )
    with pytest.raises(RuntimeError, match="exited with code 1"):
        karl.run_copilot("do something")


@patch("karl.subprocess.Popen")
def test_run_copilot_empty_lines_skipped(mock_popen):
    mock_popen.return_value = make_mock_proc(
        ["\n", "  \n", "real output\n", f"{karl.SIGNAL_COMPLETED}\n"],
    )
    with patch.object(karl.log, "info") as mock_log:
        result, output = karl.run_copilot("do something")
    assert result is True
    # Only non-empty lines should be logged (real output + SIGNAL_COMPLETED)
    assert mock_log.call_count == 2


@patch("karl.subprocess.Popen")
def test_run_copilot_builds_command_with_model(mock_popen):
    mock_popen.return_value = make_mock_proc([f"{karl.SIGNAL_COMPLETED}\n"])
    karl.run_copilot("test prompt", model="gpt-4.1")
    cmd = mock_popen.call_args[0][0]
    assert "--model" in cmd
    assert "gpt-4.1" in cmd
    assert cmd[-1] == "test prompt"
    assert cmd[-2] == "--prompt"


@patch("karl.subprocess.Popen")
def test_run_copilot_builds_command_without_model(mock_popen):
    mock_popen.return_value = make_mock_proc([f"{karl.SIGNAL_COMPLETED}\n"])
    karl.run_copilot("test prompt")
    cmd = mock_popen.call_args[0][0]
    assert "--model" not in cmd


@patch("karl.subprocess.Popen")
def test_run_copilot_failed_then_completed(mock_popen):
    mock_popen.return_value = make_mock_proc(
        [f"{karl.SIGNAL_FAILED}\n", "fixing...\n", f"{karl.SIGNAL_COMPLETED}\n"],
    )
    result, _ = karl.run_copilot("do something")
    assert result is True


@patch("karl.subprocess.Popen")
def test_run_copilot_completed_then_failed(mock_popen):
    mock_popen.return_value = make_mock_proc(
        [f"{karl.SIGNAL_COMPLETED}\n", f"{karl.SIGNAL_FAILED}\n"],
    )
    result, _ = karl.run_copilot("do something")
    assert result is False


@patch("karl.run_copilot")
def test_implement_breaks_on_success(mock_run):
    mock_run.return_value = (True, "")
    karl.implement("plan.md", "claude-opus-4.6", 50)
    assert mock_run.call_count == 1


@patch("karl.run_copilot")
def test_implement_retries_on_failure(mock_run):
    mock_run.side_effect = [(False, "")] * 3 + [(True, "")]
    karl.implement("plan.md", "claude-opus-4.6", 50)
    assert mock_run.call_count == 4


@patch("karl.run_copilot")
def test_implement_respects_max_iterations(mock_run):
    mock_run.return_value = (False, "")
    karl.implement("plan.md", "claude-opus-4.6", 5)
    assert mock_run.call_count == 5


@patch("karl.run_copilot")
def test_review_first_breaks_on_success(mock_run):
    mock_run.return_value = (True, "")
    karl.review_first("plan.md", "claude-sonnet-4.6", 2)
    assert mock_run.call_count == 1


@patch("karl.run_copilot")
def test_review_first_retries_on_failure(mock_run):
    mock_run.side_effect = [(False, ""), (True, "")]
    karl.review_first("plan.md", "claude-sonnet-4.6", 2)
    assert mock_run.call_count == 2


@patch("karl.run_copilot")
def test_review_first_respects_max_iterations(mock_run):
    mock_run.return_value = (False, "")
    karl.review_first("plan.md", "claude-sonnet-4.6", 2)
    assert mock_run.call_count == 2


@patch("karl.run_copilot")
def test_review_second_breaks_on_success(mock_run):
    mock_run.return_value = (True, "")
    karl.review_second("plan.md", "claude-sonnet-4.6", 50)
    assert mock_run.call_count == 1


@patch("karl.run_copilot")
def test_review_second_retries_on_failure(mock_run):
    mock_run.side_effect = [(False, "")] * 3 + [(True, "")]
    karl.review_second("plan.md", "claude-sonnet-4.6", 50)
    assert mock_run.call_count == 4


@patch("karl.run_copilot")
def test_review_second_respects_max_iterations(mock_run):
    mock_run.return_value = (False, "")
    karl.review_second("plan.md", "claude-sonnet-4.6", 5)
    assert mock_run.call_count == 5


@patch("karl.run_copilot")
def test_crossreview_breaks_when_fix_succeeds(mock_run):
    mock_run.side_effect = [
        (False, "issues found"),
        (True, "all fixed"),
    ]
    karl.crossreview("plan.md", "claude-opus-4.6", "gpt-5.3-codex", 50)
    assert mock_run.call_count == 2


@patch("karl.run_copilot")
def test_crossreview_loops_until_clean(mock_run):
    mock_run.side_effect = [
        (False, "issues"),
        (False, "fixed some"),
        (False, "more issues"),
        (True, "clean"),
    ]
    karl.crossreview("plan.md", "claude-opus-4.6", "gpt-5.3-codex", 50)
    assert mock_run.call_count == 4


@patch("karl.setup_logging")
@patch("karl.run_copilot")
def test_execute_plan_stops_on_setup_failure(mock_run, mock_setup_logging):
    mock_run.return_value = (False, "")
    karl.execute_plan("plan.md", "claude-opus-4.6", "claude-sonnet-4.6",
                          "gpt-5.3-codex", 50)
    assert mock_run.call_count == 1


@patch("karl.setup_logging")
@patch("karl.finalize")
@patch("karl.crossreview")
@patch("karl.review_second")
@patch("karl.review_first")
@patch("karl.implement")
@patch("karl.setup")
def test_execute_plan_runs_finalize_on_success(mock_setup, mock_implement,
                                               mock_review_first, mock_review_second,
                                               mock_crossreview, mock_finalize,
                                               mock_setup_logging):
    mock_setup.return_value = True
    karl.execute_plan("plan.md", "claude-opus-4.6", "claude-sonnet-4.6",
                          "gpt-5.3-codex", 50)
    mock_finalize.assert_called_once_with("plan.md", "claude-opus-4.6")


@patch("karl.setup_logging")
@patch("karl.finalize")
@patch("karl.setup")
def test_execute_plan_skips_finalize_on_setup_failure(mock_setup, mock_finalize,
                                                       mock_setup_logging):
    mock_setup.return_value = False
    karl.execute_plan("plan.md", "claude-opus-4.6", "claude-sonnet-4.6",
                          "gpt-5.3-codex", 50)
    mock_finalize.assert_not_called()


@patch("karl.setup_logging")
@patch("karl.finalize")
@patch("karl.crossreview")
@patch("karl.review_second")
@patch("karl.review_first")
@patch("karl.implement")
@patch("karl.setup")
def test_execute_plan_passes_max_iterations_to_review_first(mock_setup, mock_implement,
                                                              mock_review_first, mock_review_second,
                                                              mock_crossreview, mock_finalize,
                                                              mock_setup_logging):
    mock_setup.return_value = True
    karl.execute_plan("plan.md", "claude-opus-4.6", "claude-sonnet-4.6",
                          "gpt-5.3-codex", 100)
    mock_review_first.assert_called_once_with("plan.md", "claude-sonnet-4.6", max(1, 100 // 20))


def test_setup_logging_adds_handlers(tmp_path):
    test_log = karl.log
    initial_handlers = len(test_log.handlers)
    try:
        karl.setup_logging(str(tmp_path / "test.log"))
        assert len(test_log.handlers) == initial_handlers + 2
    finally:
        test_log.handlers = test_log.handlers[:initial_handlers]


def test_setup_logging_no_file():
    test_log = karl.log
    initial_handlers = len(test_log.handlers)
    try:
        karl.setup_logging(None)
        assert len(test_log.handlers) == initial_handlers + 1
    finally:
        test_log.handlers = test_log.handlers[:initial_handlers]


@patch("karl.run_copilot")
def test_finalize(mock_run):
    mock_run.return_value = (True, "")
    assert karl.finalize("plan.md", "claude-opus-4.6") is True
    assert mock_run.call_count == 1


@patch("karl.run_copilot")
def test_finalize_failure(mock_run):
    mock_run.return_value = (False, "")
    assert karl.finalize("plan.md", "claude-opus-4.6") is False


@patch("karl.run_copilot")
def test_setup_success(mock_run):
    mock_run.return_value = (True, "")
    assert karl.setup("plan.md", "claude-opus-4.6") is True


@patch("karl.run_copilot")
def test_setup_failure(mock_run):
    mock_run.return_value = (False, "")
    assert karl.setup("plan.md", "claude-opus-4.6") is False


@patch("karl.setup_logging")
@patch("karl.run_copilot")
def test_execute_plan_full(mock_run, mock_setup_logging):
    mock_run.return_value = (True, "")
    karl.execute_plan("plan.md", "claude-opus-4.6", "claude-sonnet-4.6",
                          "gpt-5.3-codex", 50)
    # setup + implement + review_first + review_second + crossreview(analyze only, breaks early) + finalize
    assert mock_run.call_count == 6



@patch("karl.execute_plan")
def test_main_custom_models(mock_execute):
    with patch("sys.argv", [
        "karl", "plan.md",
        "--main-model", "gpt-4.1",
        "--review-model", "gpt-5-mini",
        "--critic-model", "claude-haiku-4.5",
        "--max-iterations", "10",
    ]):
        with patch("pathlib.Path.exists", return_value=True):
            karl.main()
    mock_execute.assert_called_once_with(
        "plan.md", "gpt-4.1", "gpt-5-mini", "claude-haiku-4.5", 10)


@patch("karl.execute_plan")
def test_main_defaults(mock_execute):
    with patch("sys.argv", ["karl", "plan.md"]):
        with patch("pathlib.Path.exists", return_value=True):
            karl.main()
    mock_execute.assert_called_once_with(
        "plan.md", karl.MAIN_MODEL, karl.REVIEW_MODEL,
        karl.CRITIC_MODEL, karl.MAX_ITERATIONS)


@patch("karl.execute_plan")
def test_main_rejects_zero_max_iterations(mock_execute):
    with patch("sys.argv", ["karl", "plan.md", "--max-iterations", "0"]):
        with pytest.raises(SystemExit):
            karl.main()
    mock_execute.assert_not_called()


@patch("karl.execute_plan")
def test_main_rejects_negative_max_iterations(mock_execute):
    with patch("sys.argv", ["karl", "plan.md", "--max-iterations", "-1"]):
        with pytest.raises(SystemExit):
            karl.main()
    mock_execute.assert_not_called()


@patch("karl.execute_plan")
def test_main_rejects_nonexistent_plan(mock_execute):
    with patch("sys.argv", ["karl", "nonexistent.md"]):
        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(SystemExit):
                karl.main()
    mock_execute.assert_not_called()


@patch("karl.execute_plan")
def test_main_rejects_empty_model_name(mock_execute):
    with patch("sys.argv", ["karl", "plan.md", "--main-model", ""]):
        with pytest.raises(SystemExit):
            karl.main()
    mock_execute.assert_not_called()


def test_positive_int_accepts_positive():
    assert karl.positive_int("1") == 1
    assert karl.positive_int("50") == 50


def test_positive_int_rejects_zero():
    with pytest.raises(argparse.ArgumentTypeError):
        karl.positive_int("0")


def test_positive_int_rejects_negative():
    with pytest.raises(argparse.ArgumentTypeError):
        karl.positive_int("-1")


def test_positive_int_rejects_non_integer():
    with pytest.raises(argparse.ArgumentTypeError):
        karl.positive_int("abc")
    with pytest.raises(argparse.ArgumentTypeError):
        karl.positive_int("1.5")


def test_non_empty_str_accepts_valid():
    assert karl.non_empty_str("claude-opus-4.6") == "claude-opus-4.6"


def test_non_empty_str_rejects_empty():
    with pytest.raises(argparse.ArgumentTypeError):
        karl.non_empty_str("")


def test_non_empty_str_rejects_whitespace():
    with pytest.raises(argparse.ArgumentTypeError):
        karl.non_empty_str("   ")


def test_non_empty_str_strips_surrounding_whitespace():
    assert karl.non_empty_str("  claude-opus-4.6  ") == "claude-opus-4.6"


@patch("karl.run_copilot")
def test_implement_passes_model_to_run_copilot(mock_run):
    mock_run.return_value = (True, "")
    karl.implement("plan.md", "gpt-4.1", 1)
    assert mock_run.call_args[1]["model"] == "gpt-4.1"


@patch("karl.run_copilot")
def test_review_first_passes_model_to_run_copilot(mock_run):
    mock_run.return_value = (True, "")
    karl.review_first("plan.md", "gpt-4.1", 2)
    assert mock_run.call_args[1]["model"] == "gpt-4.1"


@patch("karl.run_copilot")
def test_review_second_passes_model_to_run_copilot(mock_run):
    mock_run.return_value = (True, "")
    karl.review_second("plan.md", "gpt-4.1", 1)
    assert mock_run.call_args[1]["model"] == "gpt-4.1"


@patch("karl.run_copilot")
def test_crossreview_respects_max_iterations(mock_run):
    mock_run.return_value = (False, "")
    karl.crossreview("plan.md", "claude-opus-4.6", "gpt-5.3-codex", 3)
    # 2 run_copilot calls per iteration (analyze + fix)
    assert mock_run.call_count == 6


@patch("karl.run_copilot")
def test_setup_passes_model_to_run_copilot(mock_run):
    mock_run.return_value = (True, "")
    karl.setup("plan.md", "gpt-4.1")
    assert mock_run.call_args[1]["model"] == "gpt-4.1"


@patch("karl.run_copilot")
def test_finalize_passes_model_to_run_copilot(mock_run):
    mock_run.return_value = (True, "")
    karl.finalize("plan.md", "gpt-4.1")
    assert mock_run.call_args[1]["model"] == "gpt-4.1"


@patch("karl.run_copilot")
def test_crossreview_breaks_when_analyze_succeeds(mock_run):
    mock_run.return_value = (True, "no issues found")
    karl.crossreview("plan.md", "claude-opus-4.6", "gpt-5.3-codex", 50)
    # analyze returns True → break immediately without calling fix
    assert mock_run.call_count == 1


@patch("karl.run_copilot")
def test_crossreview_uses_critic_model_for_analyze_and_main_model_for_fix(mock_run):
    mock_run.side_effect = [(False, "issues found"), (True, "all fixed")]
    karl.crossreview("plan.md", "claude-opus-4.6", "gpt-5.3-codex", 50)
    analyze_call, fix_call = mock_run.call_args_list
    assert analyze_call[1]["model"] == "gpt-5.3-codex"
    assert fix_call[1]["model"] == "claude-opus-4.6"


@patch("karl.build_crossreview_analyze_prompt")
@patch("karl.build_crossreview_fix_prompt")
@patch("karl.run_copilot")
def test_crossreview_passes_fix_stdout_to_next_analyze(mock_run, mock_fix_prompt, mock_analyze_prompt):
    mock_analyze_prompt.return_value = "analyze prompt"
    mock_fix_prompt.return_value = "fix prompt"
    mock_run.side_effect = [
        (False, "first issues"),   # analyze iteration 1
        (False, "fixed stuff"),    # fix iteration 1
        (True, "no more issues"),  # analyze iteration 2
    ]
    karl.crossreview("plan.md", "claude-opus-4.6", "gpt-5.3-codex", 50)
    # First analyze call should receive empty string as fix_stdout
    first_analyze_call = mock_analyze_prompt.call_args_list[0]
    assert first_analyze_call[0][2] == ""
    # Second analyze call should receive fix_stdout from first fix call
    second_analyze_call = mock_analyze_prompt.call_args_list[1]
    assert second_analyze_call[0][2] == "fixed stuff"
