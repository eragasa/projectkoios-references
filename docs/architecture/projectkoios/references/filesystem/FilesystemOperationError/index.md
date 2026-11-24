# `FilesystemOperationError`

`FilesystemOperationError` is the shared failure category owned by
[`projectkoios.references.filesystem`](../index.md). Concrete security failures
remain owned by descriptor, observation, scanning, publication, path, root, or
preflight operations rather than being raised as one catch-all error.

## VVUQ classification

| Evidence class | Applicability |
| --- | --- |
| `software_verification` | Applicable: tests check the implemented software contract under explicit conditions. |
| `numerical_verification` | Not applicable: no numerical scheme, discretization, convergence criterion, or mathematical solution error is evaluated. |
| `scientific_validation` | Not applicable: no physical or scientific model is compared with trusted real-world evidence. |
| `uncertainty_quantification` | Not applicable: no scientific uncertainty model is characterized or propagated. |

## Software-verification evidence

`test__filesystem_operations__raise_owner_specific_security_errors` in
`tests/package/projectkoios/references/filesystem/test__OperationErrors.py`
exercises create-only publication, symlink observation, strict directory
scanning, and authorized-root replacement. It checks the owning concrete error
type for each operation.
