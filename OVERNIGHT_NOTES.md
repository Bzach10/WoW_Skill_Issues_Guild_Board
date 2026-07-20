# Overnight improvement log

One entry per loop iteration. Everything landed on branch 2.0 only —
main is frozen on reviewed code for the 9 AM auto-post. Review in the
morning and say "merge" to take what you like.

## Iteration 1 (~3:15 AM)
Added the first tests for the Discord delivery layer: multi-file
attachment shape (files[0]/files[1] + mime by extension), 429 rate-limit
retry, and the missing-file fallback to a clean JSON post. 92 tests total.
