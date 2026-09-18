# Ingestion reference-evidence fixtures

The two JSON files in this directory are copied byte-for-byte from the
`projectkoios-ingestion` producer at commit
`33cb03bfca85ca43b073fc85de59abd896e1c7d3`.

| Fixture | Producer Git blob | Bytes | SHA-256 |
|---|---|---:|---|
| `complete.json` | `6b1f167be60c5dda4c4c45862ca579441fb7e92c` | 3685 | `56b5d0aff7f692b27700786b8828a86240be1ecb647bac7d64ad4a152d0de405` |
| `unsupported-generation.json` | `1f7d7d6756d12bcdcdac892c3e7130759106c061` | 3686 | `7ed795c742d9237434230c46b1a4e59c3ba364ce92dbf9b4f39d0b0df4f293da` |

They contain synthetic identities and no private paths, source filenames,
protected text, credentials, or access-control details. Fixture replay and
consumer conformance are implementation evidence for the **Proposed**
`projectkoios.ingestion.reference-evidence@0.1.0` contract. They do not accept
that contract or establish independent revalidation, proofreading, scientific
validity, rights, or publication authority.
