# `c04` source options — semantic integration failures

**Step 1, no spend.** `c04` targets the *semantic* class: merge clean, combined
tests fail. Four campaigns and a sweep (71 episodes, two models) produced zero.
This decides where `c04`'s episodes should come from.

---

## 1. Census: can CooperBench produce a semantic failure at all?

Method (`farm/overlap.py`, 8 tests): compare the two **gold** feature patches of
every pair. Hunk ranges are taken from the old side, because both patches are
measured against the same base and only the base's line numbers are common
ground. Four classes, reported as the strongest claim about the *merge*:

| class | meaning |
|---|---|
| `textual` | same file, hunks touching or within git's context window — git refuses |
| `same_file` | same file, hunks far enough apart that git merges cleanly |
| `semantic` | **disjoint files** sharing a symbol, type or import |
| `independent` | disjoint files, nothing shared |

### Every TypeScript pair

`react_hook_form_task` is the only TypeScript repo in CooperBench, so its 25
pairs *are* every TypeScript pair.

| class | all 25 | usable 19 |
|---|---:|---:|
| textual | 25 | **19** |
| same_file | 0 | 0 |
| **semantic** | **0** | **0** |
| independent | 0 | 0 |

The 6 unusable pairs are exactly the six EXPECTATIONS §4.3 records as
mislabelled — `has_conflict: false` only because a gold patch never applied.
Excluding them, the classifier and the dataset agree on **19 of 19**.

### The whole dataset, for context

| class | pairs | share |
|---|---:|---:|
| textual | 564 | 87.3% |
| same_file | 82 | 12.7% |
| **semantic** | **0** | **0.0%** |
| independent | 0 | 0.0% |

**Not one pair in CooperBench has disjoint files.** All 646 usable pairs across
twelve repos share at least one file. Validation: every one of the 82
`same_file` predictions has `gold_has_conflict: false` (100%), and `textual`
predicts a real conflict 499/564 times.

By repo, the `same_file` pairs — the only ones where a clean merge is
structurally possible — are concentrated:

| repo | usable | textual | same_file |
|---|---:|---:|---:|
| `pallets_jinja_task` | 135 | 97 | **38** |
| `dottxt_ai_outlines_task` | 79 | 63 | **16** |
| `pallets_click_task` | 115 | 99 | **16** |
| `dspy_task` | 55 | 49 | 6 |
| `pillow_task` | 30 | 26 | 4 |
| `go_chi_task`, `llama_index_task` | 61 | 59 | 1 each |
| `react_hook_form_task` | 19 | **19** | **0** |
| `huggingface_datasets`, `openai_tiktoken`, `dirty_equals`, `typst` | 152 | 152 | 0 |

### What this means

**CooperBench TypeScript cannot produce a semantic integration failure.** Not
"rarely" — structurally. Every usable pair's gold patches overlap textually in
`src/logic/createFormControl.ts`, and the slice has zero `same_file` pairs, so
even a *clean merge* never occurs in the gold data.

This is the explanation for 71 episodes and zero semantic failures. It was never
a sample-size problem. The benchmark pairs features **within one task**, and
CooperBench tasks are built around a single central file, so co-located edits
are the design rather than an accident.

The strongest thing CooperBench can offer is the 82 `same_file` pairs, mostly
Python (`pallets_jinja`, `dottxt`, `pallets_click`). Those merge cleanly and
*could* fail semantically — but they are same-file, so a claim map keyed on
file-level overlap would flag them anyway, which weakens them as evidence for
an engine whose value is catching what file-level tools miss.

---

## 2. Seeded semantic pairs

### What I could and could not source

The brief says "from a verified provider→consumer claim". **There is no Conetic
engine, claim map, or analyzed-corpus artefact in this repository** — every
"claim map" string in this repo is prose I wrote in earlier reports. So I cannot
cite the engine's claim IDs.

What I did instead: cloned the three corpora at HEAD and derived the
provider→consumer edges from the code itself, by parsing internal imports and
confirming each symbol's definition site and use sites. Every edge below is
real and checkable. The **`edge`** field is what should be mapped onto the
engine's own claim ID before this is called a seeded-from-claims corpus.

Repos, pinned:

| repo | commit | package used |
|---|---|---|
| `colinhacks/zod` | `eb1c108` | `packages/zod/src/v4/core` |
| `TanStack/query` | `50680b9` | `packages/query-core/src` |
| `excalidraw/excalidraw` | `854d00c` | `packages/common/src`, `packages/element/src` |

### The shape every pair has

* **A** changes the *provider's* shape and ships tests asserting the new shape.
* **B** extends a *consumer* in a **different file**, on the **old** shape, and
  ships tests asserting the behaviour it added.
* Alone, both pass. Merged, the merge is clean — disjoint files — and **B's
  tests fail**, because the contract it consumed moved underneath it.

That is a semantic failure by construction, and it is invisible to `git merge`.

### The ten

| # | repo | provider (A edits) | consumer (B edits) | edge — the symbol that couples them |
|---|---|---|---|---|
| 1 | query | `utils.ts` `hashKey` | `queryCache.ts` | `hashKey` — the query-hash string format |
| 2 | query | `utils.ts` `addToEnd`/`addToStart` | `infiniteQueryBehavior.ts` | page-window trimming semantics |
| 3 | query | `utils.ts` `timeUntilStale` | `queryObserver.ts` | clamped-at-zero staleness number |
| 4 | query | `utils.ts` `matchQuery` | `queryClient.ts` | filter-predicate semantics |
| 5 | excalidraw | `common/utils.ts` `getFontString` | `element/textElement.ts` | the CSS font shorthand string |
| 6 | excalidraw | `common/utils.ts` `arrayToMap` | `element/typeChecks.ts` | map key semantics (`id` vs value) |
| 7 | excalidraw | `common/utils.ts` `getUpdatedTimestamp` | `element/mutateElement.ts` | version/timestamp monotonicity |
| 8 | zod | `core/util.ts` `floatSafeRemainder` | `core/schemas.ts` | remainder precision for `multipleOf` |
| 9 | zod | `core/util.ts` `joinValues` | `core/errors.ts` | separator/quoting in error messages |
| 10 | zod | `core/util.ts` `getEnumValues` | `core/schemas.ts` | enum value ordering / reverse-mapping filter |

### Worked example — pair 1, in full

The other nine follow the same template; this one is spelled out so the shape is
unambiguous.

**Edge.** `hashKey(queryKey)` is defined in `packages/query-core/src/utils.ts`
and consumed in `queryCache.ts`, `queryClient.ts` and `mutationObserver.ts`. It
returns `JSON.stringify` with object keys sorted — an *observable string
contract* that callers store as `Query.queryHash`.

**Agent A — change the provider's shape.**
> Add a stable schema version to query hashes so persisted caches can be
> invalidated across releases. `hashKey` must return `"v2:"` followed by the
> current serialization. Update the existing `hashKey` tests.

A's test (its own, passing alone):
```ts
it('prefixes hashes with the schema version', () => {
  expect(hashKey(['todos', { id: 1 }])).toBe('v2:' + JSON.stringify(['todos', { id: 1 }]))
})
```

**Agent B — extend a consumer on the old shape.**
> Add `QueryCache.findAllByKeyPrefix(prefix: QueryKey)` returning every query
> whose hash begins with the serialization of `prefix`, so devtools can group
> queries by namespace.

B's test (its own, passing alone):
```ts
it('groups queries by key prefix', () => {
  const cache = new QueryCache()
  cache.build(client, { queryKey: ['todos', 1] })
  cache.build(client, { queryKey: ['todos', 2] })
  cache.build(client, { queryKey: ['users', 1] })
  // relies on the hash starting with the serialized prefix
  expect(cache.findAllByKeyPrefix(['todos'])).toHaveLength(2)
})
```

**Why the merge is clean and the combined tests fail.** A touches only
`utils.ts` (+ its test file); B touches only `queryCache.ts` (+ its test file).
Disjoint — git merges without a murmur. After the merge every hash is
`"v2:[...]"`, so B's `startsWith(JSON.stringify(prefix).slice(0, -1))` matches
nothing and `findAllByKeyPrefix` returns `[]`. **B's test fails; A's passes.**

**What the claim map should flag, and where.** A writes
`utils.ts::hashKey` (return-shape claim); B reads it at
`queryCache.ts::findAllByKeyPrefix`. One producer, one consumer, one symbol —
flagged before the merge, from the claims, with no diff overlap to notice.

### The remaining nine, in brief

2. **A**: `addToEnd(items, item, max)` drops from the *start* on overflow;
   change it to drop the *oldest by insertion order tracked separately*, so the
   returned array keeps the newest `max`. **B**: add
   `InfiniteQueryBehavior` page-window pruning that assumes the old
   `slice(1)` trimming. Merged: B's window is off by one page.
3. **A**: `timeUntilStale` returns `Infinity` for a `'static'` staleTime instead
   of clamping to `0`. **B**: add a `staleness bucket` field to
   `QueryObserver`'s result, bucketing on a finite number. Merged: B buckets
   `Infinity` into its "fresh" bucket and its assertions invert.
4. **A**: `matchQuery` treats an absent `exact` as `true` rather than `false`.
   **B**: add `QueryClient.invalidateByTag(tag)` built on `matchQuery`'s
   loose-by-default behaviour. Merged: B invalidates nothing.
5. **A**: `getFontString` emits `"{weight} {size}px {family}"` (adds weight).
   **B**: add a measurement cache in `textElement.ts` keyed on the font string,
   with a parser that expects two leading tokens. Merged: B's cache key parse
   throws or mis-keys, and every measurement misses.
6. **A**: `arrayToMap` keys by the element itself when given strings rather than
   by `id`. **B**: add an `elementsById` lookup in `typeChecks.ts` assuming
   `id` keys. Merged: B's lookups return `undefined`.
7. **A**: `getUpdatedTimestamp` returns a monotonic counter in test mode instead
   of the constant `1`. **B**: add version-ordering assertions in
   `mutateElement.ts` that rely on equal timestamps collapsing. Merged: B's
   ordering assertions break.
8. **A**: `floatSafeRemainder` switches to integer scaling by the larger of the
   two decimal counts. **B**: add a `multipleOfPrecision` diagnostic to number
   schemas relying on the old rounding. Merged: B's boundary cases flip.
9. **A**: `joinValues` quotes values and defaults the separator to `", "`.
   **B**: add an "expected one of" error formatter that splits on `"|"`.
   Merged: B's formatter produces one run-on token.
10. **A**: `getEnumValues` returns declaration order instead of filtering
    numeric reverse-mappings first. **B**: add enum introspection asserting the
    filtered ordering. Merged: B sees reverse-mapping entries it did not expect.

### What building this source actually costs

These are **specifications, not a runnable corpus**. To become episodes each
pair still needs: a task image per repo (Dockerfile, pinned commit, installed
deps, a working test command), a `feature.md` per agent, and the expert test
files committed as `tests.patch` in the CooperBench layout. That is
infrastructure work — roughly a day — before the first episode runs. It is not
a blocker, but it is not free either, and it is the main cost of choosing this
source.

---

## 3. Cost per episode with Sonnet

Measured baseline: the `s01` Sonnet arm ran **3 CooperBench `react_hook_form`
episodes at $3.946 each** (provider meter), on a repo of ~52 source files with a
vitest suite. That is the only Sonnet-on-this-harness figure that exists, and
everything below is anchored to it.

| source | $/episode | basis |
|---|---:|---|
| **CooperBench TypeScript** | **$3.95** | measured, n=3, 95% CI roughly $3.2–4.7 |
| Seeded — `query-core` | $3.00 – $4.50 | comparable repo size; narrower task (one function + tests) should mean fewer steps, but a fresh image and unfamiliar layout push the other way |
| Seeded — `zod` core | $3.00 – $4.50 | same reasoning; `zod`'s test suite is fast |
| Seeded — `excalidraw` | $5.00 – $8.00 | much larger workspace, slower suite, monorepo cross-package imports; more context per step and more steps to orient |

**Ten seeded episodes**, if drawn 4 query / 3 zod / 3 excalidraw:
**$38 – $56**, mid-point ≈ **$45**. Against a $35 hard cap that is over — the
cap would stop the run at roughly **episode 7–8**.

**Ten CooperBench TS episodes**: ≈ **$39.50**, also over $35, stopping at
about **episode 8**.

Two cost notes that matter more than the point estimates:

* The **$13.60 per-episode hold** applies to Sonnet regardless of source, and
  the balance guard refuses to start an episode when the remaining balance is
  below it. With a $35 cap and the current $13.14 balance, a top-up is needed
  before either source can run at all.
* Restricting the seeded run to **query + zod only** (dropping excalidraw)
  gives ≈ **$30–45** for ten, and keeps the whole run inside $35 at the low end.

---

## 4. The recommendation, and the choice

**Source A — CooperBench TypeScript — cannot answer the question.** Section 1 is
not an estimate; it is a census of every pair that exists. All 19 usable pairs
are `textual`, the slice has zero `same_file` pairs, and no pair in the entire
benchmark has disjoint files. Running 10 more Sonnet episodes there would cost
about $39.50 and could not produce a semantic failure however good the model is.
The only honest reason to run it is to measure something else.

**Source B — the seeded pairs — is the only one that can produce the target
class**, because the class is built into the construction: disjoint files, a
shared symbol, and a consumer written against a shape the provider then moves.

Its cost is honesty about what is being measured. A seeded pair is a
*constructed* semantic failure, so observing one confirms the harness can detect
the class and that a claim map would flag it — it does **not** measure how often
two independent agents produce one in the wild. Those are different claims and
the report must not blur them. What it does buy is the thing that has been
missing for 71 episodes: a positive control. Without one, "zero semantic
failures" cannot be distinguished from "the instrument cannot see them", and
that ambiguity currently undermines every null result the Farm has produced.

**My recommendation: Source B, restricted to `query-core` and `zod`** — skip
excalidraw for now. It is the most expensive per episode, the largest
integration effort, and its pairs are no more semantic than the other two. Ten
episodes across query and zod land near $30–45 and stay closest to the $35 cap.

A middle option worth naming, since it is cheap: run **1–2 seeded episodes as a
positive control first**. If a constructed semantic failure is detected
end-to-end, the instrument is proven and the remaining budget can go wherever
you like. If it is *not* detected, that is a harness bug worth far more than ten
more episodes of either source.

**Stopping here for your pick.** Nothing further will be spent until you choose.
