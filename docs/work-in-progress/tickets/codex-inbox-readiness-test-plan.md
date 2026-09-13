# Inbox readiness and bounded checkout

- [x] Execute the actual first workflow step against valid configuration and missing/invalid secret/URL/ref cases. Ten cases failed before the gate existed; ten pass with the gate. No network, checkout, or installation is used by the gate.
- [x] Parameterize the existing real-Git replay harness over full and actual shallow file:// clones.
- [x] Preserve remote advancement before replay; reject a real competing push without ACK or receipt on remote.
- [x] Recover a lost ACK from a fresh shallow clone without fetching Linear again or publishing another commit.
- [x] Full local suite: 289 passed; lint and types passed.
- [ ] Hosted CI on the candidate commit.
- [ ] Authorized consumer cutover and live verification on the pinned candidate. Blocked: inbox URL/token absent; no repeated paid dispatch or provisioning performed.

Measured baseline: consumer run 34752722340 spent 98 seconds on full-history checkout before failing for absent configuration. This change does not claim zero runner charges or measured production savings. It avoids checkout/install for invalid configuration and limits initial history for valid runs.
