# Ingestion reference-evidence consumer

## Contract and authority status

`projectkoios-references` owns a strict consumer adapter for the ingestion-owned
**Proposed** contract
`projectkoios.ingestion.reference-evidence@0.1.0`, record schema generation `1`
and producer generator version `1`. The current transcript artifact generation
is `1`. The producer's owner-internal transcript-batch manifest schema `2` is
not a cross-repository contract version and is not consumed by this adapter.

The adapter implementation and fixture conformance are lifecycle evidence only.
They do not accept the Proposed contract. They do not establish producer
authentication, extraction accuracy, semantic correctness, scientific validity,
human proofreading, rights, manuscript use, or publication suitability.

## Explicit injected boundary

The consumer receives exact reference-evidence files explicitly. The CLI uses a
repeatable binding:

```bash
koios-ref collection-reconcile references.bib corpus.csv managed-pdfs output \
  --collection-id example --source-revision REV \
  --reference-evidence example2026=/explicit/evidence/example2026.json
```

Each binding is `CITEKEY=PATH`. The path is an execution input and is never
serialized. The adapter does not import `projectkoios-ingestion`, inspect an
ingestion root, construct a producer path, or infer evidence from filenames.
Omitting a binding produces the explicit status
`reference-evidence-not-supplied`; it does not mean `not-ingested` or
`not-transcribed`.

A supplied binding must name an actually scanned managed PDF with the same
citekey. The record's source SHA-256, byte length, `blob:sha256:` identity, and
`application/pdf` media type must match that managed PDF. Evidence for a
missing PDF, stale bytes, another source, or a duplicate citekey/record fails
closed.

## Strict parsing and status vocabulary

Canonical producer bytes are bounded to 262,144 bytes and parsed with duplicate
field detection, bounded nesting and arrays, exact field sets, strict UTF-8,
and byte-identical canonical replay. The adapter supports only:

- contract ID `projectkoios.ingestion.reference-evidence`, version `0.1.0`,
  status `proposed`;
- record schema `1`, producer generator
  `projectkoios-ingestion-reference-evidence` version `1`;
- exact source SHA-256/blob identity, byte length, and PDF media type;
- completed extraction contract `2.2`, including manifest/document,
  extractor/configuration, artifact identity, and warnings;
- clean-transcript contract `1.0`, artifact generation `1`, status
  `automated_unreviewed`, complete layout/transcription lineage, processor and
  configuration identity, artifact/text identity, and warnings; and
- derivation-audit contract `1.0`, status `passed`, zero findings, complete
  required lineage/layer counts, scope
  `recorded_producer_derivation_audit`, and
  `independently_revalidated: false`.

A successfully bound record projects these references-side statuses. The
projection cannot be ordinarily constructed through its public dataclass
initializer; reconciliation receives it from strict adapter replay:

| Field | Value |
|---|---|
| `ingestion_status` | `completed-source-bound-reference-evidence` |
| `transcript_status` | `automated-unreviewed-with-recorded-passing-audit` |
| `contract_status` | `proposed` |
| `derivation_audit_status` | `recorded-passing` |
| `derivation_audit_scope` | `recorded_producer_derivation_audit` |
| `independently_revalidated` | `false` |

`recorded-passing` means the producer record reports a passing audit and binds
its recorded coverage. References verifies the record and source identity but
does not rerun extraction or the audit. Therefore it cannot change
`independently_revalidated` to true.

Unknown contract/schema/generator/transcript generations, noncanonical or
malformed JSON, duplicate/unknown/missing fields, unsupported or incomplete
records, inconsistent record IDs, partial lineage, contradictory statuses,
audit findings or missing coverage, unsafe paths, oversized inputs, and source
mismatches are rejected.

## Compatibility impact

The former `scan_processing_evidence` API and `--ingestion-root` CLI option are
removed because their behavior depended on producer-private layout. Callers
must inject one canonical evidence file per managed PDF. Existing reconciliation
count keys remain unchanged, but their extraction counts now increment only for
validated source-bound completed records. Output status strings use
`reference-evidence-not-supplied` instead of inferring `not-ingested` or
`not-transcribed`.

No cross-repository version is accepted or superseded. Broader package and API
version policy remains deferred to its owning issue.

## Reconciliation package binding

The exact canonical producer bytes are retained in package input evidence under
a logical citekey-derived name. A separate deterministic processing observation
records the adapter version, Proposed contract status, record identity, status
projection, audit scope, and independent-revalidation flag. The package also
binds the managed PDF digest and size and the normalized reconciliation input.
No producer workspace path is retained. The collection manifest's coverage
claims explicitly record the Proposed contract and that independent
revalidation was not performed.

Changing the reference-evidence bytes, record identity, source PDF, or status
projection changes the package identity or fails validation. Publication and
replay retain the existing create-once package behavior.

## Cross-repository fixtures

The consumer fixtures in
`tests/fixtures/ingestion-reference-evidence/` are copied byte-for-byte from
`projectkoios-ingestion@33cb03bfca85ca43b073fc85de59abd896e1c7d3`:

| Fixture | Producer blob | SHA-256 |
|---|---|---|
| `complete.json` | `6b1f167be60c5dda4c4c45862ca579441fb7e92c` | `56b5d0aff7f692b27700786b8828a86240be1ecb647bac7d64ad4a152d0de405` |
| `unsupported-generation.json` | `1f7d7d6756d12bcdcdac892c3e7130759106c061` | `7ed795c742d9237434230c46b1a4e59c3ba364ce92dbf9b4f39d0b0df4f293da` |

The complete fixture contains only synthetic identities. The awkward fixture
reports transcript generation `99` and must fail. Neither fixture contains a
source filename, private path, protected content, credential, or access detail.
