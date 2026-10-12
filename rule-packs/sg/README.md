# Singapore rule pack

- Version: see `version` in `pack.json` (bump it on every change).
- Last checked: see `last_checked`.
- Review status: **draft**. Rule logic follows the cited sources. Section references marked "to be confirmed" must be checked by local counsel before production use.

Sources are listed in `pack.json` under `sources`, each with its link. Clause texts are plain-language summaries, not quotations.

To change a rule, edit `pack.json`, bump `version`, and run `make test`. The schema in `../schema.json` and the engine tests validate every pack.
