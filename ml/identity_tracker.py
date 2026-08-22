# ---------------------------------------------------------------
# ml/identity_tracker.py  --  THE ORCHESTRATOR
#
# This is where the core principle is actually enforced:
#
#     Recognition establishes identity.
#     Tracking preserves identity.
#     Occlusion hides identity — it must NEVER change it.
#     Only a confirmed physical exit changes cart state.
#
# PER-FRAME FLOW
# ───────────────
#   1. detector.detect(frame)            -> candidate boxes  (HOW is hidden)
#   2. drop candidates outside the zone
#   3. associate candidates to existing tracks
#        centroid distance + IoU, and when that is AMBIGUOUS, fall back to
#        comparing appearance against each candidate track's LOCKED
#        identity_embedding as a tie-breaker
#   4. unmatched candidates:
#        a. try to REACQUIRE a LOST track (locked identity_embedding match)
#        b. otherwise spawn a NEW track
#   5. matched tracks:  update geometry -> visibility gate -> (recognition
#      only if NOT yet locked) -> state machine
#   6. unmatched tracks: PRESENT -> OCCLUDED -> LOST  (never REMOVED unless
#      they were already confirmed to be EXITING across the boundary)
#   7. cart = cart_state.reconcile(tracks)   (derived, never mutated)
#
# WHAT THIS MODULE DELIBERATELY NEVER DOES
# ─────────────────────────────────────────
#   • It never runs recognition on a locked track.  Not once.  There is no
#     code path that can rename a confirmed item.
#   • It never overwrites identity_embedding (Track.lock_identity refuses).
#   • It never removes an item because of low visibility, low confidence,
#     or a lost track.
#
# It is single-threaded and deterministic: process(frame) does all its work
# before returning.  That is what makes the scripted test harness able to
# replay an exact frame sequence and get an exact, reproducible outcome.
# ---------------------------------------------------------------

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from ml.cart_state import cart_lines, reconcile
from ml.config import (
    ASSOC_AMBIGUOUS_MARGIN,
    ASSOC_APPEARANCE_WEIGHT,
    ASSOC_MAX_CENTROID_DIST,
    ASSOC_MIN_IOU,
    DEOCCLUSION_VIS_JUMP,
    EXIT_BOUNDARY_MARGIN,
    EXIT_CLIP_MARGIN,
    EXIT_CONFIRM_FRAMES,
    MERGE_AREA_RATIO,
    MOVING_MIN_DISPLACEMENT,
    OCCLUDED_TO_LOST_FRAMES,
    REACQUIRE_MAX_DIST,
    REACQUIRE_SIMILARITY,
    UNCONFIRMED_PRUNE_FRAMES,
    VERIFY_MIN_GOOD_FRAMES,
    VISIBILITY_GOOD_RATIO,
    VISIBILITY_WEAK_RATIO,
    ZONE_BOTTOM,
    ZONE_LEFT,
    ZONE_RIGHT,
    ZONE_TOP,
)
from ml.detector import Detection, Detector
from ml.multi_frame_vote import vote_over_results
from ml.track import Track, TrackState

BBox = Tuple[int, int, int, int]


class IdentityTracker:
    """
    Owns the set of Tracks and advances them one frame at a time.

    Parameters
    ----------
    detector : Detector
        Anything implementing detect(frame) -> [Detection].  This class
        never inspects how detection works.
    recognizer : Recognizer
        Anything implementing analyze / embed / similarity.  Used ONLY for
        unlocked tracks (verification) and for appearance comparisons
        against already-locked identity embeddings.
    frame_size : (width, height)
    """

    def __init__(self, detector: Detector, recognizer, frame_size=(640, 480)) -> None:
        self.detector = detector
        self.recognizer = recognizer
        self.frame_w, self.frame_h = frame_size

        self.tracks: List[Track] = []
        self._next_id = 1
        self.frame_idx = 0

        # Active zone in pixels (left, top, right, bottom).
        self.zone = (
            int(ZONE_LEFT * self.frame_w),
            int(ZONE_TOP * self.frame_h),
            int(ZONE_RIGHT * self.frame_w),
            int(ZONE_BOTTOM * self.frame_h),
        )

        # Debug / UI only.
        self.last_detections: List[Detection] = []
        self.recognitions_run = 0

    # ═════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═════════════════════════════════════════════════════════════

    def process(self, frame: np.ndarray) -> None:
        """Advance the tracker by exactly one frame."""
        self.frame_idx += 1

        detections = [d for d in self.detector.detect(frame) if self._in_zone(d.centroid)]
        self.last_detections = detections

        # ── associate ─────────────────────────────────────────────
        matches, unmatched_dets, unmatched_tracks = self._associate(detections, frame)

        # ── matched tracks ────────────────────────────────────────
        for track, det in matches:
            self._update_matched(track, det, frame)

        # ── unmatched detections: reacquire a LOST track, else spawn ─
        for det in unmatched_dets:
            if not self._try_reacquire(det, frame):
                self._spawn(det)

        # ── unmatched tracks: occlusion / loss / confirmed exit ────
        for track in unmatched_tracks:
            self._update_unmatched(track)

        # ── housekeeping ──────────────────────────────────────────
        for t in self.tracks:
            t.tick_state()
        self._prune()

    def cart(self) -> Dict[str, int]:
        """The cart, DERIVED from the tracks (never stored/mutated)."""
        return reconcile(self.tracks)

    def cart_display(self) -> List[dict]:
        return cart_lines(self.tracks)

    def active_tracks(self) -> List[Track]:
        """Tracks worth drawing (everything not terminal)."""
        return [t for t in self.tracks if t.state not in TrackState.TERMINAL]

    def reset(self) -> None:
        self.tracks = []
        self._next_id = 1
        self.frame_idx = 0
        self.recognitions_run = 0
        self.detector.reset()

    # ═════════════════════════════════════════════════════════════
    # ZONE
    # ═════════════════════════════════════════════════════════════

    def _in_zone(self, centroid: Tuple[float, float]) -> bool:
        x, y = centroid
        zl, zt, zr, zb = self.zone
        return zl <= x <= zr and zt <= y <= zb

    def _at_boundary(self, centroid: Tuple[float, float]) -> bool:
        """True if the centroid sits in the exit band hugging the zone edge."""
        x, y = centroid
        zl, zt, zr, zb = self.zone
        m = EXIT_BOUNDARY_MARGIN
        return (x - zl < m) or (zr - x < m) or (y - zt < m) or (zb - y < m)

    def _clipped_by_edge(self, bbox: BBox) -> bool:
        """
        True if this box is being CUT OFF by the zone boundary.

        Why this matters: an item leaving the frame shrinks, and so does an
        item being covered up.  Measuring area alone cannot tell those apart,
        and guessing wrong is expensive in both directions — call a departure
        an occlusion and the item never leaves the cart; call an occlusion a
        departure and you delete an item that is still there.

        The box's own position resolves it: if its edge is jammed against the
        boundary, the missing pixels are outside the frame, not behind
        another object.
        """
        x, y, w, h = bbox
        zl, zt, zr, zb = self.zone
        m = EXIT_CLIP_MARGIN
        return (x - zl <= m) or (y - zt <= m) or (zr - (x + w) <= m) or (zb - (y + h) <= m)

    def _moving_outward(self, track: Track) -> bool:
        """
        True if the track's recent velocity points toward the NEAREST zone
        edge — i.e. it is heading out, not just jiggling or moving inward.
        """
        vx, vy = track.velocity()
        if abs(vx) < 0.5 and abs(vy) < 0.5:
            return False
        x, y = track.centroid
        zl, zt, zr, zb = self.zone
        # distance to each edge
        d = {"l": x - zl, "r": zr - x, "t": y - zt, "b": zb - y}
        nearest = min(d, key=d.get)
        if nearest == "l":
            return vx < 0
        if nearest == "r":
            return vx > 0
        if nearest == "t":
            return vy < 0
        return vy > 0

    # ═════════════════════════════════════════════════════════════
    # ASSOCIATION  (centroid + IoU, appearance only as a tie-breaker)
    # ═════════════════════════════════════════════════════════════

    # States whose tracks still have a meaningful bbox to match against.
    _MATCHABLE = {
        TrackState.NEW, TrackState.VERIFYING, TrackState.CONFIRMED,
        TrackState.PRESENT, TrackState.MOVING, TrackState.EXITING,
        TrackState.OCCLUDED, TrackState.REACQUIRE,
    }

    def _geo_score(self, track: Track, det: Detection) -> float:
        """
        Geometric affinity in [0, 1].  Blends IoU with normalised centroid
        proximity so that a fast-moving item with little box overlap can
        still match, and a stationary item with a shrunken (occluded) box
        still matches strongly.
        """
        iou = track.iou(det.bbox)
        dist = track.centroid_distance(det.bbox)
        if dist > ASSOC_MAX_CENTROID_DIST and iou < ASSOC_MIN_IOU:
            return -1.0  # gated out entirely
        prox = max(0.0, 1.0 - dist / float(ASSOC_MAX_CENTROID_DIST))
        return 0.5 * iou + 0.5 * prox

    def _associate(self, detections: List[Detection], frame: np.ndarray):
        """
        Two-stage association.

        STAGE 1 — geometry.  Score every (track, detection) pair on centroid
        proximity + IoU, gated by ASSOC_MAX_CENTROID_DIST / ASSOC_MIN_IOU.

        STAGE 2 — appearance, but only where it is actually needed.  When one
        item is placed on top of another, geometry alone becomes actively
        misleading: the occluder's big blob can overlap the hidden item's
        last box better than the hidden item's own shrunken sliver does.
        Geometry would then hand the wrong box to the wrong track.

        So a pair is re-scored with appearance when the situation is
        CONTENDED, meaning either:
          • a LOCKED track has 2+ candidate detections in range, or
          • a detection is claimed by 2+ LOCKED tracks.

        In that case we compare the detection's appearance against the
        track's LOCKED identity_embedding and blend:

            final = (1 - w) * geometry  +  w * appearance

        This is the appearance tie-breaker doing its job.  Note what it can
        and cannot do: it decides WHICH BOX an existing identity follows.
        It can never rename a track, and it never touches
        identity_embedding.  With a single item and a single blob nothing is
        contended, so no extra embedding is computed at all.

        Returns (matches, unmatched_detections, unmatched_tracks).
        """
        candidates = [t for t in self.tracks if t.state in self._MATCHABLE]

        # ── stage 1: geometry ─────────────────────────────────────
        geo: Dict[Tuple[int, int], float] = {}
        for ti, t in enumerate(candidates):
            for di, d in enumerate(detections):
                s = self._geo_score(t, d)
                if s >= 0.0:
                    geo[(ti, di)] = s

        # ── work out which pairs are contended ────────────────────
        dets_per_track: Dict[int, List[int]] = {}
        locked_tracks_per_det: Dict[int, List[int]] = {}
        for (ti, di) in geo:
            dets_per_track.setdefault(ti, []).append(di)
            if candidates[ti].identity_embedding is not None:
                locked_tracks_per_det.setdefault(di, []).append(ti)

        contended: set = set()
        for ti, dis in dets_per_track.items():
            if candidates[ti].identity_embedding is not None and len(dis) >= 2:
                contended.update((ti, di) for di in dis)
        for di, tis in locked_tracks_per_det.items():
            if len(tis) >= 2:
                contended.update((ti, di) for ti in tis)

        # ── stage 2: blend in appearance for contended pairs only ──
        scores = dict(geo)
        if contended:
            emb_cache: Dict[int, Optional[np.ndarray]] = {}
            w = ASSOC_APPEARANCE_WEIGHT
            for (ti, di) in contended:
                emb = self._detection_embedding(di, detections[di], frame, emb_cache)
                if emb is None:
                    continue
                sim = self.recognizer.similarity(emb, candidates[ti].identity_embedding)
                sim = max(0.0, sim)  # negative similarity is just "no match"
                scores[(ti, di)] = (1.0 - w) * geo[(ti, di)] + w * sim
            self._log_contention(contended, candidates, geo, scores)

        # ── greedy assignment, best score first ───────────────────
        matches: List[Tuple[Track, Detection]] = []
        used_t: set = set()
        used_d: set = set()
        for (ti, di) in sorted(scores, key=lambda k: scores[k], reverse=True):
            if ti in used_t or di in used_d:
                continue
            matches.append((candidates[ti], detections[di]))
            used_t.add(ti)
            used_d.add(di)

        unmatched_dets = [d for i, d in enumerate(detections) if i not in used_d]
        matched_ids = {id(candidates[i]) for i in used_t}
        unmatched_tracks = [
            t for t in self.tracks
            if t.state not in TrackState.TERMINAL and id(t) not in matched_ids
            and t.state != TrackState.LOST  # LOST handled by reacquisition
        ]
        return matches, unmatched_dets, unmatched_tracks

    def _detection_embedding(
        self,
        di: int,
        det: Detection,
        frame: np.ndarray,
        cache: Dict[int, Optional[np.ndarray]],
    ) -> Optional[np.ndarray]:
        """Appearance vector for a detection, computed at most once per frame."""
        if di in cache:
            return cache[di]
        emb = None
        try:
            crop = det.crop(frame)
            if crop.size:
                emb = self.recognizer.embed(crop)
        except Exception as e:
            print(f"[identity_tracker] association embed failed: {e}")
        cache[di] = emb
        return emb

    def _log_contention(self, contended, candidates, geo, scores) -> None:
        """Report when appearance overrode geometry — useful when tuning."""
        tis = {ti for ti, _ in contended}
        for ti in sorted(tis):
            pairs = [(di, s) for (t, di), s in scores.items() if t == ti]
            if len(pairs) < 2:
                continue
            geo_best = max(((di, geo[(ti, di)]) for di, _ in pairs), key=lambda p: p[1])[0]
            app_best = max(pairs, key=lambda p: p[1])[0]
            if geo_best != app_best:
                t = candidates[ti]
                print(f"[identity_tracker] frame {self.frame_idx}: appearance "
                      f"tie-break moved track {t.track_id} ({t.product_id}) "
                      f"from detection {geo_best} to {app_best} "
                      f"(locked-identity comparison)")

    # ═════════════════════════════════════════════════════════════
    # MATCHED TRACK UPDATE
    # ═════════════════════════════════════════════════════════════

    def _update_matched(self, track: Track, det: Detection, frame: np.ndarray) -> None:
        # ── is this blob plausibly just this item? ────────────────────
        # A blob far bigger than the item's established size is this item
        # MERGED with something else (the classic "second product placed
        # touching the first, watershed could not split them" case).  We must
        # not let it redefine the track's geometry — see MERGE_AREA_RATIO.
        if (track.observations >= 3
                and det.area > MERGE_AREA_RATIO * track.max_observed_area):
            track.note_merged_frame(self.frame_idx)
            if track.is_locked and track.state in (
                    TrackState.PRESENT, TrackState.MOVING,
                    TrackState.EXITING, TrackState.CONFIRMED,
                    TrackState.REACQUIRE):
                track.transition(TrackState.OCCLUDED, self.frame_idx,
                                 reason="merged into a larger blob — position "
                                        "not measurable, still in cart")
            return

        track.update_geometry(det.bbox, det.quality, self.frame_idx)

        if track.is_locked:
            # ── LOCKED: identity is frozen.  We only track geometry and
            #    decide whether it is present / hidden / leaving.
            #    NO recognition happens here, ever. ──────────────────
            self._locked_state_machine(track)
            return

        # ── NOT yet locked: this is the only place recognition runs ──
        if track.state == TrackState.NEW:
            track.transition(TrackState.VERIFYING, self.frame_idx,
                             reason="first detection, gathering evidence")

        self._try_verify(track, det, frame)

    # ── visibility gate + verification ───────────────────────────

    def _try_verify(self, track: Track, det: Detection, frame: np.ndarray) -> None:
        """
        THE VISIBILITY / QUALITY GATE.

            visibility > VISIBILITY_GOOD_RATIO  -> good frame: recognise and
                                                   let it vote
            WEAK .. GOOD                        -> recognise but store as
                                                   weak evidence only; it can
                                                   never trigger a lock alone
            below WEAK                          -> do not recognise at all;
                                                   bbox/last_seen already
                                                   updated, nothing else

        A lock requires VERIFY_MIN_GOOD_FRAMES good-visibility results that
        pass the existing multi_frame_vote agreement test.
        """
        vis = track.visibility_ratio

        if vis < VISIBILITY_WEAK_RATIO:
            # Too hidden to trust any classification. Stay in VERIFYING.
            return

        crop = det.crop(frame)
        if crop.size == 0:
            return

        try:
            emb, result = self.recognizer.analyze(crop)
            self.recognitions_run += 1
        except Exception as e:
            print(f"[identity_tracker] recognition failed: {e}")
            return

        track.recognition_confidence = float(result.get("top_score", 0.0))
        is_good = vis >= VISIBILITY_GOOD_RATIO
        track.add_evidence(emb, result, vis)

        if not is_good:
            # Weak evidence: recorded for context, but deliberately NOT
            # counted toward the lock decision.
            return

        # Vote over GOOD-visibility evidence only — reusing the existing
        # multi_frame_vote agreement logic (AGREE_THRESHOLD).
        good = [e for e in track.recent_embeddings if e["vis"] >= VISIBILITY_GOOD_RATIO]
        if len(good) < VERIFY_MIN_GOOD_FRAMES:
            return

        verdict = vote_over_results([e["result"] for e in good], total_frames=len(good))
        if not verdict["confident"]:
            return  # not enough agreement yet — keep verifying, guess nothing

        name = verdict["final_name"]
        ref_emb = track.best_embedding_for(name)
        if ref_emb is None:
            return

        # ── THE LOCK: written once, from the highest-visibility frame
        #    that voted for the winner.  Never overwritten again. ────
        track.lock_identity(
            product_id=name,
            embedding=ref_emb,
            confidence=float(verdict.get("vote_count", 0)) / max(len(good), 1),
            frame_idx=self.frame_idx,
        )

    # ── locked-track state machine ───────────────────────────────

    def _locked_state_machine(self, track: Track) -> None:
        """
        Decide PRESENT vs OCCLUDED vs MOVING vs EXITING for a track that
        WAS matched to a detection this frame.  Identity is untouchable
        here — this only describes the item's physical situation.
        """
        vis = track.visibility_ratio

        # CONFIRMED is momentary: once locked and seen again, it is part of
        # the cart and becomes PRESENT.
        if track.state == TrackState.CONFIRMED:
            track.transition(TrackState.PRESENT, self.frame_idx, reason="settled into cart")

        # A track we had given up on has been re-bound to a detection.
        if track.state == TrackState.REACQUIRE:
            track.transition(TrackState.PRESENT, self.frame_idx, reason="reacquired")

        # ── is the box small because it is HIDDEN, or because it is
        #    half-way OUT of the frame? ──────────────────────────────
        # A track already carrying outward-motion evidence, whose box is now
        # jammed against the boundary, is being clipped by the edge — not
        # covered up.  Treating that as occlusion is what stops a departure
        # from ever completing.  Everything else defaults to occlusion,
        # because occlusion is the safe interpretation.
        departing = (
            self._clipped_by_edge(track.bbox)
            and (track.state == TrackState.EXITING or track.exit_progress > 0)
        )

        # ── mostly hidden -> OCCLUDED (identity survives untouched) ──
        if vis < VISIBILITY_WEAK_RATIO and not departing:
            if track.state in (TrackState.PRESENT, TrackState.MOVING, TrackState.EXITING):
                track.transition(TrackState.OCCLUDED, self.frame_idx,
                                 reason=f"visibility {vis:.2f} < {VISIBILITY_WEAK_RATIO}")
            track.exit_progress = 0
            return

        # ── visible again after being hidden ─────────────────────────
        if track.state == TrackState.OCCLUDED:
            track.transition(TrackState.PRESENT, self.frame_idx,
                             reason=f"visibility recovered to {vis:.2f}")

        # ── exit evaluation: the ONLY route out of the cart ──────────
        # An occluder moving off the item makes its box snap back to full
        # size, which moves the centroid without the item moving.  That
        # frame's displacement is an artefact, so it gets no vote here.
        deocclusion_artefact = track.visibility_jump() > DEOCCLUSION_VIS_JUMP

        moving = (track.displacement() >= MOVING_MIN_DISPLACEMENT
                  and not deocclusion_artefact)
        outward = self._moving_outward(track) and not deocclusion_artefact

        if moving and outward:
            track.exit_progress += 1
        elif not moving and not deocclusion_artefact:
            track.exit_progress = 0
        # (moving but inward/sideways, or a de-occlusion frame: keep progress,
        #  don't add to it)

        at_edge = self._at_boundary(track.centroid) or self._clipped_by_edge(track.bbox)

        if track.exit_progress >= EXIT_CONFIRM_FRAMES and at_edge:
            if track.state != TrackState.EXITING:
                track.transition(TrackState.EXITING, self.frame_idx,
                                 reason=f"outward motion x{track.exit_progress} at boundary")
        elif moving:
            if track.state == TrackState.PRESENT:
                track.transition(TrackState.MOVING, self.frame_idx,
                                 reason=f"displacement {track.displacement():.0f}px")
        elif not deocclusion_artefact:
            # Settled again, wherever it is. Not leaving.
            if track.state in (TrackState.MOVING, TrackState.EXITING):
                track.transition(TrackState.PRESENT, self.frame_idx, reason="motion stopped")
            track.exit_progress = 0

    # ═════════════════════════════════════════════════════════════
    # UNMATCHED TRACK UPDATE
    # ═════════════════════════════════════════════════════════════

    def _update_unmatched(self, track: Track) -> None:
        """
        No detection matched this track this frame.

        This is the branch where the old system used to lose items.  Here,
        disappearing is treated as an OCCLUSION problem, never as a removal
        — with exactly one exception: a track we had already confirmed to be
        EXITING (outward motion, at the boundary, for several frames) that
        then vanishes has genuinely left.
        """
        track.mark_unseen_frame()
        unseen = track.frames_unseen(self.frame_idx)

        # ── never-identified candidates: safe to forget ──────────────
        if not track.is_locked:
            if unseen >= UNCONFIRMED_PRUNE_FRAMES:
                track.transition(TrackState.REMOVED, self.frame_idx,
                                 reason="unidentified candidate expired (never in cart)")
            return

        # ── the one legitimate removal path ─────────────────────────
        if track.state == TrackState.EXITING and track.exit_progress >= EXIT_CONFIRM_FRAMES:
            track.transition(TrackState.REMOVED, self.frame_idx,
                             reason="confirmed physical exit across boundary")
            return

        # ── everything else: hidden, not gone ───────────────────────
        if track.state in (TrackState.PRESENT, TrackState.MOVING,
                           TrackState.EXITING, TrackState.CONFIRMED,
                           TrackState.REACQUIRE):
            track.transition(TrackState.OCCLUDED, self.frame_idx,
                             reason="no matching detection")
            track.exit_progress = 0

        if track.state == TrackState.OCCLUDED and unseen >= OCCLUDED_TO_LOST_FRAMES:
            track.transition(TrackState.LOST, self.frame_idx,
                             reason=f"unseen {unseen} frames — STILL counted in cart")

    # ═════════════════════════════════════════════════════════════
    # REACQUISITION  (the main reason identity_embedding is kept)
    # ═════════════════════════════════════════════════════════════

    def _try_reacquire(self, det: Detection, frame: np.ndarray) -> bool:
        """
        An unclaimed detection appeared.  Before assuming it is a brand-new
        item, check whether it is a LOST item coming back into view.

        We compare the detection's appearance against each LOST track's
        LOCKED identity_embedding — the clean vector captured back when we
        could see the item properly.  This is exactly what that stored
        embedding exists for.
        """
        lost = [t for t in self.tracks
                if t.state == TrackState.LOST and t.identity_embedding is not None]
        if not lost:
            return False

        plausible = [t for t in lost
                     if t.centroid_distance(det.bbox) <= REACQUIRE_MAX_DIST]
        if not plausible:
            return False

        crop = det.crop(frame)
        if crop.size == 0:
            return False
        try:
            emb = self.recognizer.embed(crop)
        except Exception as e:
            print(f"[identity_tracker] reacquire embed failed: {e}")
            return False

        best, best_sim = None, -2.0
        for t in plausible:
            sim = self.recognizer.similarity(emb, t.identity_embedding)
            if sim > best_sim:
                best_sim, best = sim, t

        if best is None or best_sim < REACQUIRE_SIMILARITY:
            return False

        best.transition(TrackState.REACQUIRE, self.frame_idx,
                        reason=f"appearance matches locked identity (sim={best_sim:.3f})")
        # NOTE: identity_embedding is NOT updated here.  The locked vector
        # stays exactly as it was — that is the whole point.
        best.update_geometry(det.bbox, det.quality, self.frame_idx)
        return True

    # ═════════════════════════════════════════════════════════════
    # SPAWN / PRUNE
    # ═════════════════════════════════════════════════════════════

    def _spawn(self, det: Detection) -> None:
        t = Track(self._next_id, det.bbox, self.frame_idx, quality=det.quality)
        self._next_id += 1
        self.tracks.append(t)
        print(f"[identity_tracker] new candidate track {t.track_id} "
              f"at {det.bbox} (frame {self.frame_idx})")

    def _prune(self) -> None:
        """
        Drop REMOVED tracks from the live list.

        Safe because REMOVED tracks contribute nothing to the cart
        projection — the projection already excludes them, so pruning does
        not change the cart. Their transition history was already logged.
        """
        self.tracks = [t for t in self.tracks if t.state not in TrackState.TERMINAL]
