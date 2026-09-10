# ENGINE-001 — the claim map names chains it cannot justify, on real diffs

**For the Intelligence session. Not the Farm's fix** — filed here with the
evidence attached so it can be picked up without re-deriving anything.

**Status:** open. Found while mining pallets/click history (`reports/history_mining.md`).

## Symptom

Run on the constructed corpus the claim map behaves. Run on twelve months of a
real repository's diffs it emits chains that are true of the graph and false of
the code — links between changes that have nothing to do with each other, and
chains terminating in identifiers no reader would call a contract.

This is not the same complaint as `mechanism_named_by_claim_map`. That field
records the map failing to *explain* a real interaction (CE-006, CE-007). This
is the map asserting a relationship where there is none.

## The two examples

**A documentation change linked to a test helper:**

    showtype -> isolated_filesystem

    side a: "Add `shtab` to third-party contrib list (#3793)"
    side b: "Merge main into stable (#3800)"

Side a adds a project name to a list in the docs. There is no sense in which it
provides or consumes `isolated_filesystem`, which is click's test-runner
context manager.

**A chain terminating in a single-letter local:**

    format_completion -> f

    side a: "Fix `sdist` include to ship `CHANGES.md` after changelog rename"
    side b: "Add built-in PowerShell shell completion support (#3637)"

`f` is a definition node. Whatever it is, it is not a contract that one change
provides and another consumes, and a chain that ends there tells a reader
nothing they can act on.

## How common

From 352 disjoint concurrent candidate pairs in click's last twelve months,
**90 have a directed one-edge chain**. Within those 90:

| | count | share of 90 |
|---|---:|---:|
| chain terminates in a name of 1–2 characters | 6 | 7% |
| one side's subject is documentation-shaped (docs, changelog, FAQ, contrib) | 20 | 22% |
| chain contains a `test_*` node | 17 | 19% |

Terminal-name length across the 90 chains: **6 chains end in a single character**,
19 in three, 10 in four. A contract name is usually longer than a loop variable,
and the short tail is where the false positives concentrate.

`-> f` appears six times, five of them from one side: *"Move test utils to a
module and each function to its own file"*. One refactor that created many small
files, each with a local called `f`, poisoned every pair it appears in — four of
the six are the same left-hand node, `test_deprecated_usage -> f`.

## The sample

`docs/engine/claim_map_chains_click_sample.json` — all 90 one-edge chains with
both sides' commit subjects and the changed-definition counts that produced
them. It is the input to any fix and the regression set for checking one.

Reproduce with:

    python3 scripts/mine_concurrent_pairs.py --disjoint-only ...   # see reports/history_mining.md

Raw data: `farm/history/B_disjoint_chains_click.json` (all 352 candidates, with
chains at one and three edges).

## Hypotheses, in the order I would test them

1. **Locals are being indexed as definitions.** `f`, and probably the
   three-character names, look like function-scope bindings rather than
   module-level definitions. `farm/identity.py` was tightened once before for
   exactly this — the definition patterns were narrowed to module level so that
   indented `const` declarations stopped becoming graph nodes — and this looks
   like the same class of leak through a different language construct.
2. **Name collision across files is treated as identity.** The index keys by
   name, so two unrelated `f`s in two modules are one node and a chain can walk
   through the join. The `Definition` record carries a path; the lookup does not
   use it.
3. **A file with no definitions still contributes changed lines.** 187 of the
   352 candidates have one side with no indexed definitions at all — docs,
   changelog, `pyproject.toml`. Those should probably be excluded from chain
   search rather than allowed to reach through whatever enclosing node the line
   positions happen to land in.

## What would make this closed

A chain the map emits should be one a reader can check. Concretely, on the
90-chain sample:

* no chain terminating in a name that is not module-level;
* no chain where either side changed no indexed definition;
* a rate of documentation-shaped sides at or near zero, since a change to a list
  of project names provides nothing.

And the number that matters more than any of those: **the claim map has not yet
named the mechanism of either unseeded failure the Farm has produced.** CE-006's
recorded chain is `postRouter -> defaultPostSelect`, the right file and the wrong
thing inside it; CE-007's is the same chain describing a shared-database race it
cannot see. Precision on real diffs and explanation on real failures are the same
problem seen from two ends.

## What the Farm will do meanwhile

Nothing to the engine. The next campaign uses the chain as a **selection filter**
before spending, not as an explanation after: a pair with no chain is not worth
an episode, and a pair with a chain still has to be read by a person before its
failure is described. That usage tolerates the false-positive rate above; the
explanatory usage does not.
