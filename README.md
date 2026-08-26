# Money Craft

Money Craft is a portable Agent Skill for evidence-first A-share fundamental
screening, company research, earnings review, scenario valuation, and thesis
tracking. It is a controlled derivative of AI Berkshire and adds a consistent
runtime contract for Codex, Pi, Claude, and Grok.

## Runtime boundaries

- Canonical skill: `skills/money-craft/`
- Runtime: Python 3.10+, standard library only
- Structured data: optional Fuyao REST provider via `FUYAO_API_KEY` or a protected local key file
- Research output: `~/Documents/sixseven/money` by default, overridable with `MONEY_CRAFT_OUTPUT_ROOT`
- Without the provider: use official exchange filings and issuer IR sources;
  never invent missing figures
- No automatic trading, order placement, account access, or full-market dumps

The core research runtime remains standard-library-only. The optional final
report renderer uses Markdown, WeasyPrint, and pypdf from a dedicated local
environment and produces implementation-neutral `report.html` / `report.pdf`
reading artifacts.

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

See `skills/money-craft/references/providers/fuyao.md` for the supported v0.2
operations and evidence-capture contract.

## Final report rendering

Money Craft renders audited Markdown into a responsive, offline HTML report and
an A4 PDF using the `editorial-ivory` research-publication design system. The canonical Markdown,
source manifest, audit, and offline verifier remain the research truth; the
HTML/PDF are hash-bound reading renditions and cannot change the conclusion or
evidence.

Create the dedicated optional runtime once:

```bash
python3 -m venv ~/.config/money-craft/report-venv
~/.config/money-craft/report-venv/bin/python -m pip install \
  -r skills/money-craft/requirements-report.txt
```

Render only to an explicit repo-external preview or rendition directory:

```bash
~/.config/money-craft/report-venv/bin/python \
  skills/money-craft/scripts/money_craft.py report render \
  --source <revision>/report.md \
  --output-dir /tmp/money-craft-report-preview \
  --evidence-manifest <revision>/sources/sources.manifest.json \
  --audit <revision>/report.audit.json \
  --revision-manifest <revision>/REVISION.json \
  --archive-manifest <revision>/manifest.json --json

~/.config/money-craft/report-venv/bin/python \
  skills/money-craft/scripts/money_craft.py report verify \
  --source <revision>/report.md \
  --html /tmp/money-craft-report-preview/report.html \
  --pdf /tmp/money-craft-report-preview/report.pdf --json
```

The renderer embeds CSS, JavaScript, and deterministic inline SVG charts into a
single portable HTML file. Source URLs remain visible as non-navigable locators,
so opening an archived report never fetches remote assets. Direct rendering
never defaults to the canonical revision directory. See
`skills/money-craft/references/report-rendering.md` for the visual, archive, and
verification contract.

## Research and thesis workflow

After resolving the exact A-share identity and latest formal reporting period,
generate a model-free company research contract:

```bash
python3 skills/money-craft/scripts/money_craft.py research plan \
  --security 美的集团 --thscode 000333.SZ \
  --as-of 2026-08-23 --latest-report 2026-1 \
  --provider-mode auto --json
```

The plan binds the identity, dates, mandatory and conditional official-evidence
requirements, bounded Fuyao operation matrix, financial-reconciliation
contract, expected artifacts, and audit gates. It does not access the network,
create a report, or claim that any stage has completed.

Create a resumable local research run from that same plan contract:

```bash
python3 skills/money-craft/scripts/money_craft.py research init \
  --security 美的集团 --thscode 000333.SZ \
  --as-of 2026-08-23 --latest-report 2026-1 \
  --provider-mode auto --json

python3 skills/money-craft/scripts/money_craft.py research collect \
  --workspace <workspace-returned-by-init> --resume --json
```

Without `--workspace`, `init` creates a unique private run under the Money
archive without pretending that the run is a sealed report:

```text
~/Documents/sixseven/money/
└── <ticker>-<company>/
    └── <YYYY-MM-DD>/
        ├── .research/<run-id>/       # mutable Money Craft research run
        │   ├── plan.json
        │   ├── case.json
        │   ├── run-state.json
        │   ├── evidence/
        │   ├── financial-reconciliation.json
        │   ├── report.md
        │   └── thesis.md
        ├── .working/<investment-run-id>/  # formal archive staging, managed separately
        └── revisions/rNNNN/               # immutable, audit-gated final archive
```

The command-line `--output-root` takes precedence over
`MONEY_CRAFT_OUTPUT_ROOT`, which takes precedence over the default path.
`--workspace` remains available for an explicitly managed private directory.
The dynamic workspace printed by `init` is the only path that subsequent run
commands should use.

`init` is model-free and offline. It writes an immutable `plan.json`, derives
`case.json` from that plan instead of maintaining a second operation matrix,
creates draft report/thesis files, and starts an append-only `run-state.json`.
`collect` is the explicit network boundary: it executes only the bounded Fuyao
operations in the derived case, writes private non-overwriting captures, and
returns non-zero when a provider gap remains. A missing credential or a
workspace initialized with `provider-mode=disabled` fails before collection.

Official filings remain an explicit local import rather than a provider
substitute or an automatic download:

```bash
python3 skills/money-craft/scripts/money_craft.py research import-official \
  --workspace <workspace-returned-by-init> \
  --source-id S11 --file /path/to/formal-report.pdf \
  --url https://official.example/formal-report.pdf --json

python3 skills/money-craft/scripts/money_craft.py research status \
  --workspace <workspace-returned-by-init> --json

python3 skills/money-craft/scripts/money_craft.py research finalize \
  --workspace <workspace-returned-by-init> --json
```

`S11/S12/S13` are mandatory. `S18`, `S19`, and `S20` are conditional slots for
material transaction or capital-structure disclosures, official management
Q&A, and post-reporting-period material events. They do not block a run when
irrelevant, but must be imported when the corresponding fact affects the
research conclusion. Each route must also be resolved as `not-triggered` or
`imported` in `financial-reconciliation.json`; a mismatch with the captured
evidence fails finalization.

Before finalization, complete and audit the generated reconciliation artifact:

```bash
python3 skills/money-craft/scripts/money_craft.py audit reconciliation \
  <workspace-returned-by-init>/financial-reconciliation.json --json
```

The import copies a bounded PDF or HTML snapshot, records its HTTPS source,
and binds its SHA-256 without retaining the input path. `status` is offline and
recomputes provider, official-source, reconciliation, report, thesis, manifest,
audit, and receipt state from the workspace. `finalize` requires terminal
evidence, builds a metadata-only manifest, runs all four report/thesis audits
plus the reconciliation audit, and writes an immutable completion receipt only
when every audit passes. Provider gaps
remain explicit limitations; none of these commands access an account or place
a trade. Explicit repository-local workspaces must stay under the ignored
`local/research/` tree. The archive `.research/` run is private working state,
not a formal archive revision;
promotion to `.working/<investment-run-id>` and `revisions/rNNNN` remains under
the separate investment archive ledger, verifier, and seal gates.

For a repeatable thesis revision, prepare the update contract from an already
audited thesis and compare the completed revision afterward:

```bash
python3 skills/money-craft/scripts/money_craft.py thesis prepare-update \
  --previous thesis-old.md --as-of 2026-11-01 --json

python3 skills/money-craft/scripts/money_craft.py thesis diff \
  --previous thesis-old.md --current thesis-new.md --json
```

The diff fails closed on identity changes, time reversal, rewritten update
history, missing current update rows, or an invalid report/financial audit. Its
signal is a review priority, never an order or trading instruction.

### Company-level tracking archive

Persist an audited thesis update next to the company's dated research folders:

```text
~/Documents/sixseven/money/
└── <ticker>-<company>/
    ├── <YYYY-MM-DD>/revisions/rNNNN/  # immutable formal research archive
    └── tracking/
        ├── current.json               # atomic pointer to the latest tracking revision
        ├── .working/<run-id>/         # private editable update workspace
        └── revisions/tNNNN/           # read-only thesis/card/state/diff/audits/hashes
```

Create the first tracking workspace from an audited thesis, complete the three
editable files using new evidence, then seal the result:

```bash
python3 skills/money-craft/scripts/money_craft.py track init \
  --tracking-root <company-dir>/tracking \
  --previous <audited-thesis.md> \
  --source-revision <formal-revision-dir> \
  --as-of 2026-11-01 --json

python3 skills/money-craft/scripts/money_craft.py track check \
  --workspace <workspace-returned-by-init> --json

python3 skills/money-craft/scripts/money_craft.py track status \
  --tracking-root <company-dir>/tracking --json
python3 skills/money-craft/scripts/money_craft.py track verify \
  --tracking-root <company-dir>/tracking --json
```

Later `track init` calls resolve the previous thesis from `current.json`, so
`--previous` is only required for the first revision. All four commands are
offline and model-free. `track check` validates the append-only thesis diff,
both audits, state-to-thesis hypothesis/red-line parity, deterministic health
score, unresolved placeholders, checksums, and the no-trading boundary before
creating a read-only `tNNNN` and atomically advancing `current.json`. It does
not fetch evidence or write research conclusions. See
`skills/money-craft/references/tracking-workflow.md` for the complete contract
and escalation rules.

## Public data boundary

The repository distributes code, schemas, synthetic test fixtures, derived
research reports, audits, and hash-bound evidence manifests. It does not
distribute Fuyao response payloads, capture receipts, downloaded filings, or
web-page snapshots. Keep that material under the ignored
`local/evidence/<case-id>/` tree.

The Golden Cases in `artifacts/acceptance/600519/` and
`artifacts/acceptance/000333/` demonstrate this split across Shanghai and
Shenzhen listings. Each `evidence-manifest.json` records source metadata and
SHA-256 digests, while the corresponding private files remain local. Verify a
public manifest alone, or additionally verify its local evidence when available:

```bash
python3 scripts/verify_evidence.py artifacts/acceptance/600519/evidence-manifest.json --metadata-only
python3 scripts/verify_evidence.py artifacts/acceptance/600519/evidence-manifest.json --require-private
```

Acceptance cases are declared under `acceptance/cases/`. The collector only
supports the bounded Money Craft REST operations; it does not accept arbitrary
URLs or headers, and credentials never appear in a case file or command line.
Collection is non-overwriting by default and can resume an interrupted case:

```bash
python3 scripts/acceptance_case.py collect --case acceptance/cases/000333.json
python3 scripts/acceptance_case.py collect --case acceptance/cases/000333.json --resume
python3 scripts/acceptance_case.py build-manifest --case acceptance/cases/000333.json
python3 scripts/acceptance_case.py verify --case acceptance/cases/000333.json --require-private
```

Official filings listed by a case must be acquired separately from the declared
HTTPS source and placed under its private evidence root before building the
public manifest. This keeps issuer/filing review explicit instead of turning a
structured-data response into a substitute for primary disclosure.

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
or classified as irrelevant. A report-only review is recorded under `reviews`
with a fixed `through_commit`; it advances the review baseline without moving
the submodule pin or pretending report content was absorbed. Never auto-merge
upstream changes into the canonical skill.
