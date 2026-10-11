# CourseReferenceAuthorityServiceError: schematics

```mermaid
flowchart LR
    Courses[Courses-owned scope] --> References[CourseReferenceAuthorityServiceError]
    References --> API[API transport]
    References --> Search[Search projection]
    Catalog[(Schema-5 catalog)] --> References
```

The diagram shows ownership and coordination only. References validates Courses evidence, owns authority decisions, and emits immutable results. API transports results without reconstructing authority.

- [Overview](index.md)
