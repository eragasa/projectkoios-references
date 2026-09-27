# Bounded citation-key closure

## Scope and authority

Citation closure schema 5 implements `REF-CITATION-CLOSURE-01`. A successful
record establishes only that every literal citation key observed in the
declared source scope was compared with the supplied bibliography keys under
the recorded parser contract. It is **not** a claim of full TeX/LaTeX
semantics. It does not establish canonical identity, scientific support,
relevance, reading, manuscript acceptance, rights clearance, publication
acceptance, review acceptance, or contract acceptance.

`coverage_status=complete` means complete only for the syntax and source scope
below. Unsupported or ambiguous syntax never produces a complete closure or an
absence claim. It raises `CitationCoverageIncomplete`, whose deterministic
report has `coverage_status=incomplete`, a typed reason, a relative locator when
available, parser-configuration identity, mode, entrypoint, and effective-limit
identity. I/O limit failures remain the separate typed
`ReferenceIOLimitError` with incomplete coverage.

## Versioned parser contract

`projectkoios-bounded-latex-citation-observer@2` is a literal, bounded scanner,
not a macro expander or TeX engine. `CitationParserConfiguration` schema 1 is
stored in full and content identified in every closure.

The default configuration recognizes these exact single/multi-key commands:

- LaTeX/BibLaTeX forms: `cite`, `Cite`, `autocite`, `Autocite`, `parencite`,
  `Parencite`, `textcite`, `Textcite`, `footcite`, `footcitetext`, `smartcite`,
  `Smartcite`, and `supercite`;
- common natbib forms: `citep`, `citet`, `citealp`, `citealt`, `citeauthor`,
  `citeyear`, and `citeyearpar`;
- multi-cite forms: `cites`, `Cites`, `autocites`, `Autocites`, `parencites`,
  `Parencites`, `textcites`, `Textcites`, `footcites`, `smartcites`, and
  `Smartcites`; and
- `nocite`, including the literal `*` wildcard.

Single forms accept at most two balanced, control-free optional arguments
followed by one literal braced comma-separated key list. Multi-cite forms accept
repeated optional-argument/key-list units under the same restriction; a TeX
control inside an optional note is incomplete rather than silently skipped.
Keys must use the repository's portable
citekey syntax. `*` is valid only in `nocite`; `nocite{*}` resolves every
supplied bibliography key for citation-key closure while retaining any other
explicit undefined keys.

Aliases are not inferred from source macros. A caller may supply an exact
alias-to-supported-command map in `CitationParserConfiguration`; that complete
map is bound into identity. Configured names use the same TeX control-word
syntax as the scanner (an ASCII letter followed only by ASCII letters or `@`),
so names containing digits are rejected rather than partially observed. Source
`newcommand`/`renewcommand`/`providecommand`
definitions are parsed without expanding their replacement bodies. Invocation
of any command defined this way is incomplete unless its exact name is an
explicitly configured alias; redefining a parser-recognized command is also
incomplete. Common LaTeX3/robust command and environment definition forms, and
other low-level command-definition forms, are unsupported and incomplete.

Unescaped `%` comments are skipped. Literal `verb`/`Verb` spans and the exact
configured `verbatim`, `verbatim*`, `Verbatim`, `lstlisting`, `minted`, and
`comment` environments are skipped. Unterminated regions are incomplete.
Citation-like unknown commands, nonliteral/dynamic keys or include targets,
conditional commands, `csname`, unsupported include systems, malformed groups,
and parser-bound exhaustion are incomplete rather than ignored.

## Source-selection modes and include graph

The caller must choose one mode explicitly:

- `build-graph` requires one normalized root-relative `.tex` entrypoint. Only
  the entrypoint and literal `input`/`include` targets reachable from it are
  citation-relevant. Targets are resolved from the declared manuscript root,
  matching a build launched there rather than changing resolution by including
  file. Literal `includeonly` in the entrypoint filters `include`
  edges but not `input` edges. A declaration elsewhere, missing target, path
  escape, non-TeX target, or cycle is incomplete. Unreachable templates and
  inactive `include` targets do not affect citation results or closure identity.
- `all-files-observation` forbids an entrypoint and explicitly observes every
  bounded `.tex` file below the declared root. It is not represented as a build.
  Literal include edges are recorded, and missing literal targets prevent a
  complete observation.

Every recorded path and `path:line:column` locator is normalized and relative to
the declared manuscript root. No source excerpt or private absolute root is
retained.

## Identity, bounds, and verification

A closure identity binds:

- schema, complete-coverage status, authority boundary, and limitations;
- declared mode and normalized entrypoint;
- asserted source-revision label and, when valid, clean local Git commit/tree
  verification evidence;
- root storage/preflight evidence;
- the full parser configuration, parser version, and configuration identity;
- the full effective I/O profile and its identity;
- supplied bibliography keys, explicit citation uses, commands, relative
  locators, resolution sets, and `nocite` state;
- literal include/input graph and `includeonly` selection; and
- every citation-relevant source's relative path, exact byte length, and SHA-256.

Any relevant source-byte change therefore changes closure identity. In
`build-graph` mode, changes to unreachable templates do not. An asserted
revision remains only an assertion unless the root is local, the assertion is a
full object ID equal to `HEAD`, Git reports the entire repository clean, and
every citation-relevant source byte identity matches a regular blob at its exact
repository-relative path in that tree. Ignored or otherwise untracked active
sources therefore prevent verified-tree evidence. Git or any other external
consumer is never invoked for a cloud-backed root.
Cloud-placeholder preflight, descriptor-confined reads, symlink/root/leaf-race
checks, UTF-8 checks, per-file/total/file-count/depth/token/citation limits, and
no implicit hydration remain in force. Bibliography cardinality is rejected
before normalization, and citation occurrences are rejected while parsing,
before an over-limit parsed file can be retained. Local Git cleanliness output
is streamed as NUL-delimited evidence under the recorded text-byte,
text-entry-byte, and entry-count bounds plus an explicit timeout; overflow,
malformed output, timeout, or command failure omits verified-tree evidence.

Collection reconciliation schema 5 binds the closure JSON and every relevant
source identity into package inputs. Candidate state receives only the
`citation_status` value plus exact closure identity. Acquisition, review,
asset, coverage, and ingestion evidence remain separate authority domains.
