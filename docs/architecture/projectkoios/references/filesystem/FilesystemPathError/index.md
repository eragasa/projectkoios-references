# `FilesystemPathError`

`FilesystemPathError` owns portable relative-path and root-alias validation
failures under [`projectkoios.references.filesystem`](../index.md).

## VVUQ classification

| Evidence class | Applicability |
| --- | --- |
| `software_verification` | Applicable: tests check the implemented software contract under explicit conditions. |
| `numerical_verification` | Not applicable: no numerical scheme, discretization, convergence criterion, or mathematical solution error is evaluated. |
| `scientific_validation` | Not applicable: no physical or scientific model is compared with trusted real-world evidence. |
| `uncertainty_quantification` | Not applicable: no scientific uncertainty model is characterized or propagated. |

## Software-verification evidence

`test__validate_relative_path__requires_normalized_portable_form` in
`tests/package/projectkoios/references/filesystem/path/test__FilesystemPathValidation.py`
checks traversal, absolute paths, backslashes, redundant components, reserved
segments, trailing nonportable characters, and non-NFC paths while retaining
valid normalized Unicode paths.
