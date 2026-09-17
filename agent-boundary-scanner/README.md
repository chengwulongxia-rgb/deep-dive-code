# Agent Boundary Scanner

> Static checks for the project files most likely to turn an untrusted repository into an execution path.

This is a small defensive experiment prompted by the September 2026 RubyGems/RubyDoc incident. It **does not execute project code**, install dependencies, parse remote URLs, or attempt exploitation. It reads local text files and flags three trust-boundary patterns:

1. **npm lifecycle scripts** — `preinstall`, `install`, `postinstall`, `prepublish`, and `prepare` can execute project-controlled code during an install.
2. **YARD `.yardopts --load`** — documentation builds can load a Ruby file selected by the repository.
3. **Privileged pull-request workflows** — `pull_request_target` combined with a checkout of `github.event.pull_request.head.sha` gives contributor-controlled code access to the privileged workflow context.

The scanner is deliberately narrow. A finding means *inspect this boundary before allowing an agent, CI runner, docs builder, or package tool to cross it*; it is not proof of malicious intent.

## Run it

```bash
cd agent-boundary-scanner
uv run python boundary_scanner.py fixtures/risky-package
```

Machine-readable report:

```bash
uv run python boundary_scanner.py /path/to/project --json
```

PNG severity chart (the parent directory is created if needed):

```bash
uv run python boundary_scanner.py fixtures/risky-package --chart artifacts/risk-summary.png
```

Run the tests:

```bash
uv run --group dev python -m pytest tests/ -q
```

## Reproducible fixture

`fixtures/risky-package/` is inert test data. A scan reports exactly one critical and two high-severity findings:

```text
critical=1 high=2 medium=0 low=0
[CRITICAL] .github/workflows/publish.yml: A privileged pull-request workflow checks out contributor-controlled code.
[HIGH] .yardopts: YARD can load project-controlled Ruby during documentation generation.
[HIGH] package.json: Package lifecycle scripts can execute project-controlled code during installation.
```

## Limits

- This is not a sandbox, malware detector, or full supply-chain security product.
- It intentionally does not execute a script to learn what it does.
- It only covers the three explicit patterns above; absence of findings is not a safety guarantee.
- Workflow detection is text-based so the tool stays dependency-free and inspectable.

## Source context

- HN discussion: [OpenAI agents carried out an undisclosed attack on RubyGems](https://news.ycombinator.com/item?id=49666735)
- Technical incident coverage: [JFrog’s GemStuffer analysis](https://research.jfrog.com/post/gemstuffer-openai-rubygems/)

The useful lesson is independent of attribution: a repository-controlled file becomes dangerous when a higher-privilege system automatically interprets it.
