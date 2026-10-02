# Path-safety debt boundary

The immediate unresolved debt is that generic filesystem and path-safety
responsibilities have accumulated into an oversized References module. Some or
all of those responsibilities may be misplaced in this repository, but no
replacement owner, package, shared framework, or migration has been decided.

Until an architecture-first ownership investigation is authorized and completed,
References remains the implementation owner and every existing protection and
consumer boundary remains in force.

Detailed evidence and exit criteria are recorded in
[Ownership and simplification](ownership-and-simplification.md).
