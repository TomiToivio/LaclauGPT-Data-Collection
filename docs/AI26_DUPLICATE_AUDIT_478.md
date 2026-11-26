# Finding duplicates that already exist in AI26 records (#478)

`canonicalize_source_url()` now folds the X/Twitter host family and drops X share parameters, so a *new*
capture of one post lands on one identity however it was spelled. That fix cannot tell anyone what is
**already** duplicated: the store was keyed on the raw URL for months, and the pairs written before it are
still there.

Removing one of two documents is a data decision — which one survives, and what happens to anything already
attached to the other — so this repository ships an audit, not a repair.

## Usage

```bash
python -m laclaugpt_data_collection.duplicate_audit \
    --mongodb-uri "$LACLAUGPT_MONGODB_URI" --database "$LACLAUGPT_MONGODB_DATABASE" \
    --show-groups
```

```
12582 documents · 12578 distinct identities · 4 duplicate identit(ies) (4 extra document(s))
  x.com/status/1988706380480385470: 2 docs ['6ada21c985cf548aec73df1d', '6adae01d85cf548aec740ab3'] platforms={'web': 1, 'x': 1}
  x.com/status/2001686747185394148: 2 docs [...] platforms={'web': 1, 'x': 1}
  x.com/status/2087865707165860336: 2 docs [...] platforms={'web': 2}
  x.com/status/1862598063275061484: 2 docs [...] platforms={'web': 1, 'x': 1}
```

`--json` emits the same report as an object; `--limit` bounds how many groups are listed.

## What it prints, and what it deliberately does not

A duplicate group is described by the identity's host and numeric status id, the `_id`s a repair would have
to choose between, the platforms involved and the collection methods. It never prints post text, author
handles or full URLs, so the output can be pasted into an issue or a handoff without leaking corpus content.

It also prints counts only when `--show-groups` is absent, which is the shape a monitoring cron wants.

## What it measures

- **documents / distinct identities / duplicate identities / extra documents** — the four numbers that say
  whether the corpus holds the same source twice;
- **groups**, ordered by size, when asked — the list a repair decision needs;
- nothing about *analysis*: whether a duplicate has been analysed is a separate question, answered by
  `ai26__analysis_results` and the throughput ledger.

## One residual it reports rather than hides

The store's identity keeps the case of an X screen name, so `x.com/Example_User/status/<id>` and
`x.com/example_user/status/<id>` are still two identities even though X treats them as one account. The audit
reports what the store does; it does not quietly fold something the store does not fold, because an audit that
normalises differently from the writer reports a corpus nobody is storing.

## Related

- `docs/AI26_CORPUS_DENOMINATORS.md` — what counts as a record, and why a duplicate is not a second post.
- The end-to-end acceptance of #478 (a real capture from each localhost, traced through analysis to the
  dashboard) is not affected by this tool and remains blocked on host access.
