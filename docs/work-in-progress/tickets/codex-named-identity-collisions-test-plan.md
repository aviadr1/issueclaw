# Distinct named identities must coexist

Real production replay retained one Document because another UUID already owned
its title-derived path. Names are presentation, not unique identity. Preserve
the existing owner; disambiguate the new owner's path with its full ID.

- [x] Matrix: Document/Initiative, exact/slug-equivalent names, webhook/isolated replay/pull/create. Exercise actual writers, fake only Linear. Both contents and mappings survive. 18 failures before fix; 24 matrix tests pass after.
- [x] Repeat after original owner removal keeps the disambiguated path stable.
- [x] Foreign/unmapped fallback paths remain protected, including isolated replay.
- [x] Existing issue ownership/alias guards remain unchanged.
- [ ] Full Python tests, formatting, lint, types and hosted CI.
- [ ] Real failed document prepares without changing the other owner's bytes; publish via hosted replay and verify receipt/ACK.

One resolver in SyncState owns collision selection; write_entity remains the
authoritative ownership/content check. Callers must report the selected path.
