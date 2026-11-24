# `AuthorizedRootIdentity`

`AuthorizedRootIdentity` is the frozen root-identity record owned by
[`projectkoios.references.filesystem`](../index.md). It contains the normalized
path, reporting label, device/inode and mount identity, and immutable preflight
evidence. It retains no live probe, descriptor, or operation capability.

## VVUQ classification

| Evidence class | Applicability |
| --- | --- |
| `software_verification` | Applicable: tests check the implemented software contract under explicit conditions. |
| `numerical_verification` | Not applicable: no numerical scheme, discretization, convergence criterion, or mathematical solution error is evaluated. |
| `scientific_validation` | Not applicable: no physical or scientific model is compared with trusted real-world evidence. |
| `uncertainty_quantification` | Not applicable: no scientific uncertainty model is characterized or propagated. |

## Software-verification evidence

`test__root_identity__contains_no_live_probe_or_operation_capability` in
`tests/package/projectkoios/references/filesystem/root/test__RootComposition.py`
checks the exact dataclass fields and proves that probe, read, and write
capabilities are absent.
