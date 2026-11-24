# `AuthorizedRoot`

`AuthorizedRoot` is the frozen runtime capability owned by
[`projectkoios.references.filesystem`](../index.md). It composes immutable
observation, scanning, and publication collaborators over one authorized root
identity; it does not inherit those operation roles.

## VVUQ classification

| Evidence class | Applicability |
| --- | --- |
| `software_verification` | Applicable: tests check the implemented software contract under explicit conditions. |
| `numerical_verification` | Not applicable: no numerical scheme, discretization, convergence criterion, or mathematical solution error is evaluated. |
| `scientific_validation` | Not applicable: no physical or scientific model is compared with trusted real-world evidence. |
| `uncertainty_quantification` | Not applicable: no scientific uncertainty model is characterized or propagated. |

## Software-verification evidence

`tests/package/projectkoios/references/filesystem/root/test__RootComposition.py`
verifies that:

- the capability uses composition rather than operation-role inheritance;
- identity, probe, observation, scanning, publication, and descriptor bindings
  cannot be reassigned after authorization; and
- a failed cross-root reassignment cannot make the capability report one root
  while reading another.

The exact adversarial regression is
`test__authorized_root__cannot_rebind_identity_operations_or_probe`.
