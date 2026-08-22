# Persistent-identity tracking — how it works, how to test it, what's still broken

This explains the layer that replaced frame-by-frame reclassification. Four things, in
order: how the state machine kills the overlap bug, what the identity lock actually is,
how to run the accuracy harness, and what is still genuinely weak.

The rule everything below serves:

> Recognition establishes identity. Tracking preserves identity. Occlusion hides
> identity — it must never change it. Only a confirmed physical exit changes cart state.

---

## 1. Why "Product B covers Product A" no longer corrupts the cart

The old failure had a simple shape. Every frame, the system cropped whatever it saw and
asked the classifier "what is this?" When you set the shampoo down on top of the rice,
the rice's crop changed — half of it was now shampoo pixels — so the embedding changed,
so the answer changed. The cart followed the answer. One item became two, or the wrong
one, or nothing.

The fix is that after a certain moment, **nothing can ask that question again about that
item.** Here is the same physical sequence, frame by frame, through the actual states.

**Rice goes down. Track 1 is born as `NEW`.** The detector reports a blob. It reports
only a box, an optional mask, and a quality number — it does not know or say what the
blob is. A `Track` object is created to remember this blob across frames. It has
`product_id = None`. It counts toward nothing; the cart is still empty.

**Track 1 → `VERIFYING`.** On the next frame the same blob is matched to the same track
by centroid distance and IoU, and now recognition is allowed to run — because this track
is not locked yet. Each result goes into a temporary buffer, `recent_embeddings`, tagged
with how visible the item was on that frame. Nothing about the cart changes. The system
is gathering evidence, not deciding.

**Track 1 → `CONFIRMED`, and the lock happens.** Once five *good-visibility* frames have
accumulated (visibility above 70%), they are put through the existing
`multi_frame_vote.vote_over_results` majority test. If at least three agree on "chawal",
the track locks: `product_id = "chawal"`, and `identity_embedding` is written once from
the single highest-visibility frame that voted for the winner. `Track.lock_identity()`
then refuses every future write, and the evidence buffer is thrown away — it has done its
job. Cart now reads `chawal: 1`. **This is the last moment at which the identity of this
track was decidable.** After this, no code path in the system can rename track 1.
`_update_matched()` checks `if track.is_locked:` and routes straight to the state
machine, which never touches identity.

**Track 1 → `PRESENT`.** Locked and seen again. Settled, sitting in the cart.

**Shampoo arrives on top. This is the frame that used to break everything.** Three
things go wrong at once, and each has a specific defence:

*The blob merges.* The detector often reports rice-plus-shampoo as one big region —
watershed can't always split them. If track 1 accepted that box as its own, its position
and size would be corrupted, and later, when the shampoo left, the shrinking blob would
drag track 1's centroid toward the frame edge and look exactly like the rice walking out.
That is not hypothetical — it happened during testing, and the stationary rice track
reached `EXITING`, one frame away from a false removal. So `_update_matched()` checks the
box against `MERGE_AREA_RATIO`: any detection more than 1.35× the track's established size
is treated as a *merged observation*. The track takes exactly one fact from it — proof the
item is still there, so `last_seen` refreshes and it never drifts toward `LOST` — and
refuses to measure position from it. That's the identity lock's principle applied to
geometry: an ambiguous observation must not change cart state.

*The rice's own box shrinks.* Where the blobs do separate, the visible rice area drops.
`visibility_ratio` (current area ÷ largest area ever cleanly observed) falls below 0.40.

*Recognition would now be wrong.* It isn't run. Track 1 is locked, so it isn't even
eligible.

**Track 1 → `OCCLUDED`.** The state machine sees visibility below the weak threshold and
transitions `PRESENT → OCCLUDED`. Critically, `is_counted()` returns `True` for
`OCCLUDED` — every state except `REMOVED` counts. **The cart still reads `chawal: 1`.**
`exit_progress` is reset to zero, so being covered can never accumulate toward an exit.

**Meanwhile the shampoo becomes track 2** and walks the same road independently: `NEW` →
`VERIFYING` → locked as "shampoo" → `PRESENT`. Cart reads `chawal: 1, shampoo: 1`. Two
identities, two tracks, no interference.

**If the rice stays hidden long enough: `OCCLUDED` → `LOST`.** After 18 frames with no
usable detection, the track is marked `LOST` — and the transition reason literally says
"STILL counted in cart", because `LOST` is in `TrackState.COUNTED`. A track disappearing
is not evidence of removal. It is evidence of nothing.

**Shampoo lifted off. Rice reappears.** One of two things happens. If the rice was still
matching detections, its visibility recovers and `OCCLUDED → PRESENT` with no recognition
run and no chance of a rename. If it had gone `LOST`, the reappearing blob arrives as an
unmatched detection, and `_try_reacquire()` compares its appearance against each `LOST`
track's **locked** `identity_embedding` — the clean vector from when we could see it
properly. Above 0.60 similarity and within 240px, the track re-binds: `LOST` →
`REACQUIRE` → `PRESENT`. The locked embedding is deliberately *not* updated on
reacquisition.

There is one more artefact here worth knowing about, because it caused a real false
removal during testing. When the occluder moves off, the rice's box snaps back to full
size in a single frame, which moves its centroid several dozen pixels — while the rice sat
perfectly still. The old logic read that as motion. `visibility_jump()` now detects the
upward visibility step (`DEOCCLUSION_VIS_JUMP = 0.22`) and disqualifies that frame's
displacement from counting as motion evidence.

**The only way out.** For the rice to leave the cart it must, across at least three
consecutive frames, move more than 7px per frame *and* have its velocity pointed at the
nearest zone edge, reaching `MOVING` → `EXITING`, and *then* vanish. Only in
`_update_unmatched()`, only for a track already in `EXITING` with `exit_progress >=
EXIT_CONFIRM_FRAMES`, does `REMOVED` happen. Every other way of disappearing routes to
`OCCLUDED`.

So the answer to "why doesn't overlap corrupt the cart" is that overlap and removal are no
longer expressed in the same vocabulary. Overlap produces low visibility, merged blobs,
and missing detections — all of which mean *hidden*. Removal requires sustained,
direction-checked motion across a boundary followed by disappearance. There is no
accidental path from the first set to the second.

---

## 2. `identity_embedding` vs `recent_embeddings`

Two buffers, opposite purposes, and keeping them separate is the point.

`recent_embeddings` is **evidence being weighed**. It's a short, temporary list built only
while a track is unlocked, capped at 10 entries, each tagged with the visibility of the
frame it came from. It exists so that a decision can be made from several independent
looks at the item rather than one lucky or unlucky frame — weak-visibility frames go in
for context but are excluded from the vote. The moment the track locks,
`clear_evidence()` deletes the whole thing. It is scaffolding, and scaffolding comes
down.

`identity_embedding` is **a decision already made**. One vector, copied with
`np.array(..., copy=True)` so nothing can mutate it by reference, taken from the single
best-visibility frame that voted for the winner — deliberately the *cleanest view we ever
had*, not the most recent one. `lock_identity()` hard-refuses to overwrite it and prints
a warning if anything tries.

Why they must not be the same thing: a rolling buffer of recent appearance would, by
construction, drift toward whatever the item looks like *now*. And "now" is exactly when
the item is half-covered by another product, lit differently, or partly out of frame — the
moments when its appearance is least trustworthy. An identity that updates itself is an
identity that can be argued out of existence by bad frames. So the locked vector is
frozen at its best moment and used only for questions that can't change it: *which of
these two boxes is mine?* (the appearance tie-breaker during association) and *is this
returning blob me?* (reacquisition). Both answer "where is this identity", never "what is
this identity".

---

## 3. Running the accuracy harness

`test_scripted.py` replays a fixed action sequence and scores each step. Three modes,
because *where* a failure happens matters as much as whether it happened.

```bash
cd <project root>

# Default. Real MOG2 + watershed + the real matcher, rendered scene, no camera needed.
python3 test_scripted.py --mode synthetic --script scripts/basic_overlap.txt

# Perfect detector (ground-truth boxes). Isolates tracking/identity/cart logic.
python3 test_scripted.py --mode oracle --script scripts/basic_overlap.txt

# Your webcam + the real TFLite recognizer. Press SPACE to advance each step.
python3 test_scripted.py --mode live --script scripts/basic_overlap.txt
```

Three scripts ship with it: `scripts/basic_overlap.txt` is your exact scenario (add rice,
cover it with shampoo, remove shampoo, remove rice); `scripts/hide_and_reveal.txt` covers
an item with a grey "hand" long enough to reach `LOST` and asserts it stays counted;
`scripts/reposition.txt` slides an item right across the surface and back and asserts the
cart doesn't move. A script is one step per line: `label | expected cart | scene`, where
scene items are `name@x,y,w,h`. Add your own — that's the intended way to reproduce a bug
you hit in real use.

Add `--save-frames out/` to write an annotated PNG per step using the same overlay as the
live demo, which is the fastest way to see *why* a step went wrong.

The metrics block at the end reports Correct ADDs, Correct REMOVEs, **FALSE cart
changes**, and Uncertain/no-action, scored per step by comparing the cart before and
after. The scoring encodes your target mindset directly: if the cart ends up exactly as
expected that's `CORRECT`; if it didn't change at all when it should have, that's
`UNCERTAIN` — counted separately, and treated as a pass, because declining to act is
safe; anything else is a `FALSE-CHANGE`. Only a false change sets a non-zero exit code,
so this drops into CI as-is.

Current state on this machine, headless:

| script | mode | ADDs | REMOVEs | false | uncertain |
|---|---|---|---|---|---|
| basic_overlap | oracle | 2/2 | 2/2 | 0 | 0 |
| basic_overlap | synthetic | 1/2 | 1/1 | **0** | 1 |
| hide_and_reveal | oracle | 1/1 | 1/1 | 0 | 0 |
| hide_and_reveal | synthetic | 1/1 | 1/1 | **0** | 0 |
| reposition | oracle | 2/2 | 2/2 | 0 | 0 |
| reposition | synthetic | 2/2 | 2/2 | **0** | 0 |

Zero false cart changes in every mode. That's the property worth protecting.

**Don't trust the metrics alone.** The merge-guard bug above was found by reading the
state-transition log, not by the score — the metrics were already green because the false
`EXITING` happened to reverse one frame before it would have completed a removal. So when
you run this on real footage, skim the `->` transition lines too. A locked track that ever
enters `MOVING` or `EXITING` while the item physically did not move is a bug, even if the
cart came out right that time.

---

## 4. What is still weak — read this before you trust it

**Watershed cannot separate heavily overlapping items, and this is not a tuning problem.**
That single synthetic miss above is step 2, "add shampoo covering chawal". Oracle mode
passes the same step, which localises the failure precisely: the tracking and identity
logic handle it correctly, the *detector* never produces a second box for it. The reason
is geometric. The distance transform splits a blob by finding a concave waist between two
lobes. The union of two heavily overlapping rectangles has no waist — at *any* threshold.
I measured it: for round items, splits appear at `DET_DT_RATIO = 0.65` for about 15%
overlap and 0.75 for about 27%, but for boxy items at high overlap there is nothing to
cut. In practice: **an item placed squarely on top of another may simply never be added.**
That's a miss, not a corruption, and the cart stays truthful about what it does know — but
it is a real hole, and it is the reason `detector.py` is behind a swappable `Protocol`. A
trained detector is the actual fix; drop it in behind `detect(frame) -> [Detection]` and
nothing downstream changes.

**`DET_DT_RATIO` is a two-sided risk, and I set it conservatively.** Raising it improves
separation but a single tall bottle can have two distance lobes and get split into two
tracks — which double-counts one item. A missed second item is a safe failure; a double
count is a false cart change. It's at 0.65. Tune it with your real products in front of
the camera, and when in doubt go lower. Note the comment in `config.py` used to claim
lower splits more aggressively; that was backwards, and I've corrected it with the
measured numbers.

**MOG2 absorbing stationary items is mitigated, not eliminated.** The background now
learns fast for the first 40 frames and very slowly after (`DET_WARMUP_RATE = 0.05`, then
`DET_LEARNING_RATE = 0.0006`), because absorbing a placed item too fast caused a real bug:
the item stopped being detected, and the next disturbance produced a 35px sliver whose
wandering centroid spawned a duplicate track. Slow learning trades that for vulnerability
to lighting drift. If phantom blobs appear as the room's light changes, raise the rate; if
placed items stop being detected, lower it.

**The merge guard trades a dangerous failure for a safe one, and the safe one is real.**
`MERGE_AREA_RATIO` is now 1.35, tightened from 1.6 after the near-miss described above. The
cost is that a track's size baseline only ever grows by that factor per frame, so an item
whose first few frames were partly covered can end up permanently rejecting its own true
full-size box — it sits at visibility 0, goes `OCCLUDED` then `LOST`, and **stays counted**
in the cart, but its stale position may cost it a later removal. That's an "uncertain",
which is the failure I chose. I deliberately did not add an escape hatch that re-bases the
baseline after N merged frames, because two items that genuinely sit together for a while
would then re-corrupt the surviving track's geometry — reintroducing exactly the false-
removal path the guard exists to close.

**Occlusion-vs-exit rests on a heuristic.** A shrinking box near the frame edge is read as
a departure only if the track already carries outward-motion evidence, otherwise it's read
as occlusion. That asymmetry is deliberate and makes the safe error the default, but a
genuinely unusual exit — an item lifted straight up out of frame with no lateral travel —
won't register as a removal. It'll sit in the cart as `LOST`. Watch for that.

**None of this has met a real webcam.** Every number above comes from rendered scenes and
ground-truth boxes; there is no camera and no TFLite runtime in the environment I built
this in. Real lighting, real shadows, real hands entering the frame, and real product
embeddings are all untested. `--mode live` is the run you need to do, and I'd expect the
visibility gates and `REACQUIRE_SIMILARITY` to need re-tuning once you do — those two are
the parameters most exposed to real-world appearance variation. Every threshold is a named
constant in `ml/config.py` with a comment explaining which direction to move it and why.

**Also honest about the hand.** MOG2 sees a hand as motion like anything else, so a hand
reaching in can spawn a candidate track. It never reaches a lock, because the matcher won't
confidently vote a hand as a product, and unlocked tracks are pruned after 12 unseen frames
without ever touching the cart. `hide_and_reveal.txt` asserts this. But it's a
recognition-rejection guarantee, not a structural one — if your matcher ever votes
confidently on a hand, it would lock. A real detector trained on your products would close
that too.
