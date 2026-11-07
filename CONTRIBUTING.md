# Contributing

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export SFM_TEST_DSN=postgresql://postgres:...@localhost:5432/scratch
make check
```

## Adding or changing a rule

1. Write the corpus cases first: the source, the Snowflake output you expect, the status and the
   rules. Check the output against Snowflake's documentation and say in the PR what you checked.
2. Implement the rule in `rules/teradata.py` or `rules/oracle.py`, with a `describe(...)` entry
   and a note for every change it makes.
3. If the meaning on Snowflake can differ and intent is unknowable, translate faithfully and use
   a `warning`, not a rewrite.
4. Regenerate `docs/examples` with `make examples` and run `make eval`.

## Adding a database adapter

Implement `columns`, and if needed `count`, `aggregates` and `rows`, in
`validate/adapters.py`, with a byte-wise `text_order` for text keys. Add a test against a real
instance if CI can run one; otherwise mark it as untested in the README.
