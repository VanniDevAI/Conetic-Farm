# The pair census, as a manifest

`results/census_resolved.json` records what 652 CooperBench pairs were
classified as. It does not record what was measured — which repository, which
commit, which tree the pair's two gold patches produce — so every row in it is
an assertion a reader has no way to check. This manifest is those rows with
their sources attached.

`manifest.jsonl`, one line per pair:

| field | what it is |
|---|---|
| `repo`, `upstream`, `task`, `features` | which pair |
| `base_sha` | the commit the task image checks out, read from its Dockerfile, always full-length |
| `lane_sha` | base plus **one** gold patch, per feature: one lane's branch |
| `head_sha` | the two lane commits **merged**, or `null` when git refuses |
| `head_sha_note` | why there is no head, when there is none |
| `conflicted_paths` | the files git refused on |
| `label` | the resolved class, the census's own verdict |
| `label_diff_only` | the class before the identity graph resolved symbols |
| `has_link`, `link` | the chain of definitions connecting the two patches |

Every commit is made with a fixed author, committer and date, so the same base
and the same two patches always produce the same forty characters. Verified: an
independent re-run of `go_chi_task` reproduces all 22 rows byte for byte.

A head is computed as a real merge of two lane commits, not by applying one
patch and then the other. Sequential application conflates a patch that is
broken against the base with a patch that is fine against the base and collides
with its partner, and the second is the entire thing the census counts.

## The manifest disagrees with the classifier 65 times

`summary.json` carries the tally. Set against what git actually does:

| classifier says | git merges | git refuses |
|---|---:|---:|
| `same_file` | 82 | **0** |
| `textual` | **65** | 505 |

`same_file` is exactly right, 82 for 82. `textual` is wrong 65 times in 570 —
**11.4%** — and always in the same direction: the classifier calls a pair
conflicting when git merges it.

The cause is a deliberate choice, now measured. `farm/overlap.py` calls two
hunks in one file textual when they touch **or abut within a context window**,
because git needs context lines between hunks and a pair separated by less than
one conflicts even though its changed lines do not overlap. `tests/test_overlap.py`
states the reasoning: calling such a pair clean "would be wrong in the direction
that matters." That is still true. What was not known is the size of the error
in the other direction, and it is 11.4%.

The number is not new, and its agreement is the point. `results/all_pair_overlap_summary.json`
already carried `textual|False: 65` from the dataset's own `gold_has_conflict`
labels, which were produced by actually merging the gold patches. This manifest
merged two lane commits with git, on a fresh clone, from the other direction —
and landed on **the same 65**. Two independent methods, one count. What the
manifest adds is that each of those 65 now has a `base_sha`, two `lane_sha`
values and a `head_sha`, so a pair can be checked out and graded rather than
only counted.

**Which matters, because the merge-clean population of the corpus is 147 pairs,
not 82** — 22.5% rather than 12.6%. Appendix F read the 65 as an accuracy
statistic about the classifier. Read the other way they are the only place in
the existing corpus where a semantic failure could be hiding: a clean merge
whose combined tree is broken is exactly the class the campaign has spent four
episodes constructing by hand. None of the 147 has been graded.

## Rebuilding it

    python3 scripts/export_census_manifest.py

Clones each repository blobless once, checks out each task's base commit,
builds one commit per feature and one merge per pair, and deletes the clone
before the next repository. Resumable: a repository whose rows are already
present is not cloned again. 652 rows in about three minutes.
