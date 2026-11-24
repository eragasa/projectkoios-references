# `MacOSFileProviderPlaceholderProbe`

`MacOSFileProviderPlaceholderProbe` is the immutable, unbound File Provider
probe factory owned by
[`projectkoios.references.adapters.filesystem.macos`](../index.md). It declares
support and binds a separate immutable observation capability to an authorized
root inode; the factory itself has no candidate-observation operation.

## VVUQ classification

| Evidence class | Applicability |
| --- | --- |
| `software_verification` | Applicable: tests check the implemented software contract under explicit conditions. |
| `numerical_verification` | Not applicable: no numerical scheme, discretization, convergence criterion, or mathematical solution error is evaluated. |
| `scientific_validation` | Not applicable: no physical or scientific model is compared with trusted real-world evidence. |
| `uncertainty_quantification` | Not applicable: no scientific uncertainty model is characterized or propagated. |

## Software-verification evidence

`test__macos_probe_factory__returns_separate_immutable_bindings` in
`tests/package/projectkoios/references/filesystem/root/preflight/test__MacOSProbeBinding.py`
verifies sequential reuse, sixteen concurrent bindings, distinct returned
capabilities, immutable factory and bound state, rejection of an inode mismatch,
and absence of a fake `observe` method on the unbound factory.
