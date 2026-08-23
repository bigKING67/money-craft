# Money Craft

Money Craft is a portable Agent Skill for evidence-first A-share fundamental
screening, company research, earnings review, scenario valuation, and thesis
tracking. It is a controlled derivative of AI Berkshire and adds a consistent
runtime contract for Codex, Pi, Claude, and Grok.

## Runtime boundaries

- Canonical skill: `skills/money-craft/`
- Runtime: Python 3.10+, standard library only
- Structured data: optional Fuyao REST provider via `FUYAO_API_KEY` or a protected local key file
- Without the provider: use official exchange filings and issuer IR sources;
  never invent missing figures
- No automatic trading, order placement, account access, or full-market dumps

The API key must be supplied through the process environment or the protected
local file below. Do not pass it on the command line, put it in a repository
file, or include it in a report.

```bash
install -d -m 700 ~/.config/money-craft
# Write the key without putting it in shell history, then restrict it to the current user.
read -rs 'FUYAO_API_KEY?Fuyao API key: '; printf '%s\n' "$FUYAO_API_KEY" > ~/.config/money-craft/fuyao-api-key; unset FUYAO_API_KEY
chmod 600 ~/.config/money-craft/fuyao-api-key
python3 skills/money-craft/scripts/money_craft.py doctor --json
python3 skills/money-craft/scripts/money_craft.py data search --query 贵州茅台
```

See `skills/money-craft/references/providers/fuyao.md` for the supported v0.1
operations and evidence-capture contract.

## Public data boundary

The repository distributes code, schemas, synthetic test fixtures, derived
research reports, audits, and hash-bound evidence manifests. It does not
distribute Fuyao response payloads, capture receipts, downloaded filings, or
web-page snapshots. Keep that material under the ignored
`local/evidence/<case-id>/` tree.

The 600519 Golden Case in `artifacts/acceptance/600519/` demonstrates this
split. `evidence-manifest.json` records source metadata and SHA-256 digests,
while the corresponding private files remain local. Verify the public manifest
alone, or additionally verify the local evidence when it is available:

```bash
python3 scripts/verify_evidence.py artifacts/acceptance/600519/evidence-manifest.json --metadata-only
python3 scripts/verify_evidence.py artifacts/acceptance/600519/evidence-manifest.json --require-private
```

Fixtures under `tests/fixtures/fuyao/` are synthetic contract examples, not
captured market data.

## Host discovery

Codex, Pi, and Grok discover the shared Agent Skills user root. Install the
canonical copy there:

```bash
python3 scripts/install_skill.py --host agents
```

Claude Code 2.1.x discovers personal standalone Skills from
`~/.claude/skills/`, not `~/.agents/skills/`. Install its compatibility copy
separately:

```bash
python3 scripts/install_skill.py --host claude
```

Use `--force` only after reviewing an existing installation; the installer
creates a timestamped backup before replacement. `--target-root` supports an
isolated acceptance test. Every installation is a symlink-free atomic copy with
`INSTALL_PROVENANCE.json`; credentials are never copied into a Skill directory.

## Validation

```bash
npm test
npm run validate
npm run package-check
npm run host-smoke
```

The default host smoke is model-free: Codex is checked through its model-visible
prompt catalog, Pi through a fresh offline RPC `get_commands`, and Grok through
`inspect --json`. Claude Code is checked through its compatibility installation
hash and installed runtime self-test because 2.1.x exposes no model-free personal
Skill discovery command. Therefore `fresh_session_tested` remains false and the
Claude result is explicitly partial; no host model is invoked and no model usage
is incurred. `npm run host-smoke:static` keeps the manifest-only check.

These gates validate source, package, and local discovery behavior. Fuyao live
access and paid fresh-session host behavior remain separate evidence layers and
must not be claimed from static or model-free validation alone.

## Upstream updates

AI Berkshire is pinned under `upstreams/ai-berkshire`. Run:

```bash
python3 scripts/upstream_status.py --fetch --json
```

The command is read-only with respect to Money Craft source. Review each change
and update `sources.lock.json` only when it is intentionally absorbed, deferred,
or classified as irrelevant. Never auto-merge upstream changes into the
canonical skill.
