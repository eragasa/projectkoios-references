# `CourseReferenceAuthorityLoadActionizer` schematic

```text
validated immutable inputs
        |
        v
CourseReferenceAuthorityLoadActionizer
        |
        v
typed immutable owner boundary
```

For an Actionizer, the only executable edge is `Request -> action(request=...) -> Result`. For a passive contract, construction performs validation only.
