# `ReferenceAuthorityReceiptActionizer` schematic

```text
validated immutable inputs
        |
        v
ReferenceAuthorityReceiptActionizer
        |
        v
typed immutable owner boundary
```

For an Actionizer, the only executable edge is `Request -> action(request=...) -> Result`. For a passive contract, construction performs validation only.
