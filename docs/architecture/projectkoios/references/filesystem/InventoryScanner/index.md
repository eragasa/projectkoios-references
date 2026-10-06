# `InventoryScanner`

`InventoryScanner` owns bounded traversal that retains typed incompleteness
under [`projectkoios.references.filesystem`](../index.md). It returns canonical,
deterministically ordered valid files and typed issues instead of converting a
partial inventory into apparent complete coverage.

## VVUQ classification

| Evidence class | Applicability |
| --- | --- |
| `software_verification` | Applicable: tests check the implemented software contract under explicit conditions. |
| `numerical_verification` | Not applicable: no numerical scheme, discretization, convergence criterion, or mathematical solution error is evaluated. |
| `scientific_validation` | Not applicable: no physical or scientific model is compared with trusted real-world evidence. |
| `uncertainty_quantification` | Not applicable: no scientific uncertainty model is characterized or propagated. |

## Software-verification evidence

`test__inventory__retains_nonportable_issue_and_continues_traversal` in
`tests/package/projectkoios/references/filesystem/scanning/test__InventoryTraversal.py`
creates `CON.pdf` alongside valid `alpha.pdf` and `zeta.pdf`. It verifies that:

- the reserved name becomes a `NONPORTABLE_NAME` issue;
- valid files remain deterministically ordered; and
- traversal continues with the exact entry count retained.
