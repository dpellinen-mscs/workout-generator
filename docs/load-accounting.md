# Workout load accounting

The seven-day display counts completed exercise rows dated from today minus six
days through today, inclusive. Future, invalid, missing, and older dates do not
contribute. An unlogged displayed workout contributes its planned score and
pattern counts once. Once its session identity appears anywhere in history,
only eligible completion rows contribute; reopening an old completion does not
turn it into a new plan.

Web sessions use the existing database workout ID, so identical workouts saved
as distinct sessions remain distinct. Completed rows recover each block's
original exercise metadata and intensity from that user's saved `workout_json`.
Matching uses category and exercise ID (name when IDs are absent), in logging
order, including repeated accessory exercises when every matching row is present.
If deletion or duplicate rows make that mapping ambiguous, those rows use the
legacy estimate below rather than guessing their original intensity. No schema or data migration is
required. This preserves mixed intensities, power exercises, and metadata for
exercises subsequently renamed or removed from the current library.

Legacy rows without matching saved metadata use the current exercise library
(all groups, including power), matched by exercise ID or name, with phase-based
intensity. Unknown exercises contribute neither load nor patterns because their
metadata cannot be recovered. These legacy estimates cannot reconstruct a lost
block intensity. Rows without session identity cannot suppress a displayed plan.

New CLI JSON saves carry a UUID session identity inside the workout and at the
top level, and completion rows retain exercise metadata and block intensity.
Resaving the same workout retains its identity; independently generated equal
workouts receive different identities. Legacy CLI files keep their existing
whole-file hash identity; their older top-level payload hash is not substituted.
Repeated CLI logging now returns without appending duplicate rows.

This remains the application's configured heuristic score, not a validated
physiological measure. No benchmark, split-selection, or prescription math changes.

Historical duplicate completion rows remain separate contributions; this patch
does not deduplicate or migrate existing history. Sequential new repeat logs are
prevented, but the existing web check-then-insert race under simultaneous submits
is unchanged.
