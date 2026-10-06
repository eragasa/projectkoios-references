# `CitationKeyError`

`CitationKeyError` is owned by
[`projectkoios.references.citation.key`](../index.md), independently of
filesystem-operation errors.

## VVUQ classification

| Evidence class | Applicability |
| --- | --- |
| `software_verification` | Applicable: tests check the implemented software contract under explicit conditions. |
| `numerical_verification` | Not applicable: no numerical scheme, discretization, convergence criterion, or mathematical solution error is evaluated. |
| `scientific_validation` | Not applicable: no physical or scientific model is compared with trusted real-world evidence. |
| `uncertainty_quantification` | Not applicable: no scientific uncertainty model is characterized or propagated. |

## Software-verification evidence

`test__validate_citekey__rejects_nonportable_values` in
`tests/package/projectkoios/references/citation/key/test__CitationKeyValidation.py`
checks empty, traversal-shaped, absolute, separator-bearing, reserved,
non-normalized, non-ASCII, and over-limit citation keys.
