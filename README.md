# Karl

Plan-driven coding automation using GitHub Copilot CLI.

Write a markdown plan with tasks and checkboxes — Karl executes it end-to-end: implementation, multi-pass code review, cross-model adversarial review, and git history cleanup.

## How It Works

```
plan.md → setup → implement → review → cross-review → finalize
```

1. **Setup** — initializes git repo if needed, auto-commits any plan-related changes, creates a feature branch. Stops with an error if unrelated uncommitted changes are detected (stash, commit, or discard them first)
2. **Implement** — picks the first uncompleted task section, implements it, marks checkboxes done, repeats until all tasks are complete
3. **Review (two passes)** — first pass runs 5 parallel review agents (quality, implementation, testing, simplification, documentation); second pass focuses on critical/major issues only. Both loop until a clean pass
4. **Cross-review** — adversarial review between two models: one analyzes, the other evaluates and fixes. Loops until the analyzer finds nothing
5. **Finalize** — rebases onto the default branch, squashes commits, runs final tests

## Plan Format

Plans are markdown files with `### Task N:` sections containing `[ ]` checkboxes:

```markdown
# Feature Name

## Description
What this feature does.

## Context
Language, framework, testing tools, relevant details.

## Tasks

### Task 1: Set up module
- [ ] Create the main file with core functions
- [ ] Add error handling

### Task 2: Add CLI
- [ ] Add argparse interface
- [ ] Print results to stdout

### Task 3: Write tests
- [ ] Test all functions
- [ ] Test error cases
```

## Usage

```bash
# Execute a plan
python karl.py plan.md

# Override models
python karl.py plan.md --main-model claude-opus-4.6 --review-model claude-sonnet-4.6 --critic-model gpt-5.3-codex

# Set max iterations per step
python karl.py plan.md --max-iterations 20
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `plan` | (required) | Path to the markdown plan file |
| `--main-model` | `claude-opus-4.6` | Model for implementation and fixes |
| `--review-model` | `claude-sonnet-4.6` | Model for code review passes |
| `--critic-model` | `gpt-5.3-codex` | Model for cross-review analysis |
| `--max-iterations` | `50` | Max iterations per step (must be >= 1) |

## Requirements

- Python 3
- [GitHub Copilot CLI](https://github.com/github/copilot-cli) (`copilot` binary in PATH)
- Git

## Project Structure

```
karl.py          # main script — pipeline orchestration
prompts/             # prompt templates for each pipeline phase
  setup.txt          # git/branch initialization
  implement.txt      # task implementation loop
  review_first.txt   # full review (5 agents)
  review_second.txt  # focused review (2 agents)
  crossreview_analyze.txt  # cross-model analysis
  crossreview_fix.txt      # cross-model fix evaluation
  finalize.txt       # rebase and cleanup
agents/              # review agent personas (inlined into prompts via {{agent:name}})
  quality.txt        # bugs, security, correctness
  implementation.txt # requirement coverage
  testing.txt        # test coverage and quality
  simplification.txt # over-engineering detection
  documentation.txt  # documentation gaps
docs/                # example plans and reference
```

## Acknowledgments

Inspired by [Ralphex](https://github.com/ralphex).
