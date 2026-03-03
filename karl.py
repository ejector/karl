#!/usr/bin/env python3
"""Karl — Plan-driven Copilot automation."""

import argparse
import logging
import os
import subprocess
import re
import sys
from datetime import datetime
from pathlib import Path



_SCRIPT_DIR = Path(__file__).resolve().parent
WORK_DIR = ".karl"
PROMPTS_DIR = _SCRIPT_DIR / "prompts"
AGENTS_DIR = _SCRIPT_DIR / "agents"

MAIN_MODEL = "claude-opus-4.6"
REVIEW_MODEL = "claude-sonnet-4.6"
CRITIC_MODEL = "gpt-5.3-codex"

MAX_ITERATIONS = 50

SIGNAL_COMPLETED = "<<<KARL:DONE>>>"
SIGNAL_FAILED = "<<<KARL:FAILED>>>"

log = logging.getLogger("karl")


def ts(msg):
    return f"[{datetime.now().strftime('%y-%m-%d %H:%M:%S')}] {msg}"


def setup_logging(progress_file):
    fmt = logging.Formatter("%(message)s")
    log.setLevel(logging.DEBUG)

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(fmt)
    log.addHandler(stdout_handler)

    if progress_file:
        file_handler = logging.FileHandler(progress_file)
        file_handler.setFormatter(fmt)
        log.addHandler(file_handler)


def run_copilot(prompt, model: str = None) -> tuple[bool, str]:
    cmd = ["copilot", "--yolo", "--silent", "--no-color"]
    if model:
        cmd.extend(["--model", model])
    cmd.extend(["--prompt", prompt])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    result = False
    output = ""

    try:
        for line in proc.stdout:
            output += line
            text = line.rstrip("\n\r")
            if not text.strip():
                continue
            if SIGNAL_COMPLETED in text:
                result = True
            if SIGNAL_FAILED in text:
                result = False
            log.info(ts(text))
    except Exception:
        proc.terminate()
        raise
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait()
            except Exception as e:
                log.warning("Failed to wait for killed process: %s", e)

    if proc.returncode != 0:
        raise RuntimeError(f"copilot exited with code {proc.returncode}")

    return result, output


def expand_agents(prompt, agents_dir):
    """Replace {{agent:name}} placeholders with file contents from agents_dir."""
    agents_dir = Path(agents_dir).expanduser()

    def replace(match):
        name = match.group(1)
        path = agents_dir / f"{name}.txt"
        if not path.exists():
            log.warning("agent file not found: %s", path)
            return match.group(0)
        return f"--- {name} ---\n{path.read_text(encoding='utf-8').strip()}\n--- end ---\n"

    return re.sub(r"\{\{agent:([a-zA-Z0-9_-]+)\}\}", replace, prompt)


def build_setup_prompt(plan_path: str) -> str:
    prompt = (PROMPTS_DIR / "setup.txt").read_text(encoding="utf-8")
    return prompt.replace("{{PLAN_FILE}}", plan_path)


def build_finalize_prompt(plan_path: str) -> str:
    prompt = (PROMPTS_DIR / "finalize.txt").read_text(encoding="utf-8")
    return prompt.replace("{{PLAN_FILE}}", plan_path)


def progress_file_for(plan_path: str) -> str:
    stem = Path(plan_path).stem
    return f"{WORK_DIR}/.progress_{stem}.txt"



def build_implementation_prompt(plan_path: str) -> str:
    prompt = (PROMPTS_DIR / "implement.txt").read_text(encoding="utf-8")
    return prompt.replace("{{PLAN_FILE}}", plan_path)\
        .replace("{{PROGRESS_FILE}}", progress_file_for(plan_path))


def build_review_first_prompt(plan_path: str) -> str:
    prompt = (PROMPTS_DIR / "review_first.txt").read_text(encoding="utf-8")
    prompt = prompt.replace("{{PLAN_FILE}}", plan_path)\
        .replace("{{PROGRESS_FILE}}", progress_file_for(plan_path))
    prompt = expand_agents(prompt, AGENTS_DIR)
    return prompt


def build_review_second_prompt(plan_path: str) -> str:
    prompt = (PROMPTS_DIR / "review_second.txt").read_text(encoding="utf-8")
    prompt = prompt.replace("{{PLAN_FILE}}", plan_path)\
        .replace("{{PROGRESS_FILE}}", progress_file_for(plan_path))
    prompt = expand_agents(prompt, AGENTS_DIR)
    return prompt


def build_crossreview_analyze_prompt(plan_path: str, model: str, model_review_output: str) -> str:
    prompt = (PROMPTS_DIR / "crossreview_analyze.txt").read_text(encoding="utf-8")
    return prompt\
        .replace("{{PLAN_FILE}}", plan_path)\
        .replace("{{MODEL_NAME}}", model)\
        .replace("{{REVIEW_CONTEXT}}", model_review_output)


def build_crossreview_fix_prompt(plan_path: str, model: str, model_review_output: str) -> str:
    prompt = (PROMPTS_DIR / "crossreview_fix.txt").read_text(encoding="utf-8")
    return prompt\
        .replace("{{PLAN_FILE}}", plan_path)\
        .replace("{{MODEL_NAME}}", model)\
        .replace("{{REVIEW_CONTEXT}}", model_review_output)


def setup(plan_path: str, main_model: str) -> bool:
    result, _ = run_copilot(build_setup_prompt(plan_path), model=main_model)
    return result


def finalize(plan_path: str, main_model: str) -> bool:
    result, _ = run_copilot(build_finalize_prompt(plan_path), model=main_model)
    return result


def implement(plan_path: str, main_model: str, max_iterations: int):
    log.info("Implementing plan from %s...", plan_path)
    for iteration in range(max_iterations):
        log.info("--- implement %d ---", iteration)
        result, _ = run_copilot(build_implementation_prompt(plan_path), model=main_model)
        if result:
            break


def review_first(plan_path: str, review_model: str, max_iterations: int):
    log.info("Running first-pass code review (up to %d iterations)...", max_iterations)
    for iteration in range(max_iterations):
        log.info("--- review_first %d ---", iteration)
        result, _ = run_copilot(build_review_first_prompt(plan_path), model=review_model)
        if result:
            break


def review_second(plan_path: str, review_model: str, max_iterations: int):
    log.info("Running second-pass code review (up to %d iterations)...", max_iterations)
    for iteration in range(max_iterations):
        log.info("--- review_second %d ---", iteration)
        result, _ = run_copilot(build_review_second_prompt(plan_path), model=review_model)
        if result:
            break


def crossreview(plan_path: str, main_model: str, critic_model: str, max_iterations: int):
    log.info("Running cross code review (up to %d iterations)...", max_iterations)
    fix_stdout = ""
    for iteration in range(max_iterations):
        log.info("--- crossreview %d ---", iteration)
        analyze_prompt = build_crossreview_analyze_prompt(plan_path, main_model, fix_stdout)
        analyze_code, analyze_stdout = run_copilot(analyze_prompt, model=critic_model)
        if analyze_code:
            break

        fix_prompt = build_crossreview_fix_prompt(plan_path, critic_model, analyze_stdout)
        fix_code, fix_stdout = run_copilot(fix_prompt, model=main_model)

        if fix_code:
            break


def execute_plan(plan_path: str, main_model: str, review_model: str,
                 critic_model: str, max_iterations: int):
    os.makedirs(WORK_DIR, exist_ok=True)
    setup_logging(progress_file_for(plan_path))

    if not setup(plan_path, main_model):
        return

    implement(plan_path, main_model, max_iterations)
    review_first(plan_path, review_model, max(1, max_iterations // 20))
    review_second(plan_path, review_model, max(3, max_iterations // 10))
    crossreview(plan_path, main_model, critic_model, max(3, max_iterations // 5))

    finalize(plan_path, main_model)


def positive_int(value):
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value} is not an integer")
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is not a positive integer")
    return ivalue


def non_empty_str(value):
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("model name must not be empty")
    return stripped


def main():
    parser = argparse.ArgumentParser(
        prog="karl",
        description="Execute a markdown plan using GitHub Copilot CLI.",
    )
    parser.add_argument("plan", help="path to the markdown plan file")
    parser.add_argument("--main-model", default=MAIN_MODEL, type=non_empty_str,
                        help=f"model for implementation (default: {MAIN_MODEL})")
    parser.add_argument("--review-model", default=REVIEW_MODEL, type=non_empty_str,
                        help=f"model for reviews (default: {REVIEW_MODEL})")
    parser.add_argument("--critic-model", default=CRITIC_MODEL, type=non_empty_str,
                        help=f"model for cross-review (default: {CRITIC_MODEL})")
    parser.add_argument("--max-iterations", type=positive_int, default=MAX_ITERATIONS,
                        help=f"max iterations per step, must be >= 1 (default: {MAX_ITERATIONS})")
    args = parser.parse_args()

    if not Path(args.plan).exists():
        parser.error(f"plan file not found: {args.plan}")

    execute_plan(args.plan, args.main_model, args.review_model,
                 args.critic_model, args.max_iterations)


if __name__ == "__main__":
    main()