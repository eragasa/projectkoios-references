# `AssetApplicationOperationRequest`

Immutable typed request containing exact plan, authorization, identity,
search-root, destination, and optional catalog capabilities plus the proposed
citekey selector, optional relative candidate selector, and bounded rights
observation.

Every path has an explicit storage class. Catalog path and storage class are
all-or-none; search-root aliases are unique; candidate paths remain confined
relative paths. Request construction rejects incomplete capabilities before
reading inputs or mutating the destination or catalog.

Evidence: [implementation](../implementation.md).
