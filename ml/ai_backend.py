# ---------------------------------------------------------------
# ml/ai_backend.py  --  ASK A VISION MODEL THE SAME 1-vs-1 QUESTION
#
# WHY THIS FILE EXISTS  (read this first)
# ────────────────────────────────────────
# This is the SECOND verifier, built to be compared against the first.  It
# answers the identical question ml/verifier.py answers —
#
#       "The scanner says SKU X.  Is this item X?"
#
# — but by sending one crop to a vision-language model instead of scoring a
# MobileNet embedding and a colour histogram.  It returns the SAME
# VerdictResult with the SAME five verdicts, so compare_backends.py can score
# both on one yardstick.
#
# ONE CLIENT, TWO DESTINATIONS
# ─────────────────────────────
# OpenRouter (cloud) and Ollama (local) both expose the OpenAI-compatible
# /chat/completions endpoint, so this one class covers both and only the base
# URL changes:
#
#     cloud  ->  https://openrouter.ai/api/v1   + OPENROUTER_API_KEY
#     local  ->  http://localhost:11434/v1      (key ignored)
#
# That is the whole reason the endpoint is a config knob: you can answer "is a
# VLM even more accurate than MobileNet on MY products?" for about a cent of
# cloud credit BEFORE deciding whether to buy hardware to host one.
#
# WE USE requests, NOT AN SDK
# ────────────────────────────
# requests is already a dependency of this project and the call is a single
# POST with a JSON body.  An extra SDK would add install weight to a 2 GB Pi
# and buy nothing we need.
#
# FAIL CLOSED — THE RULE THAT MATTERS MOST HERE
# ──────────────────────────────────────────────
# This backend talks to a network service and parses model-generated text.
# Both are unreliable in ways the local path simply is not.  So EVERY failure
# mode — no key, no network, timeout, HTTP error, truncated body, invalid
# JSON, missing fields, a model that ignores the schema — resolves to RETRY,
# never MATCH.  An accept is only ever returned when the model actually,
# explicitly and confidently said "yes, that is the product".
#
# Nothing here is wired into the live checkout path.  Today this is a
# comparison subject; whether it earns a place in the lane is a decision for
# the numbers compare_backends.py prints.
# ---------------------------------------------------------------

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

from ml.config import (
    AI_BACKEND_BASE_URL,
    AI_BACKEND_MAX_SIDE,
    AI_BACKEND_MODEL,
    AI_BACKEND_TIMEOUT_SEC,
    VERIFY_MIN_USABLE_FRAMES,
)
from ml.verifier import Verdict, VerdictResult
from ml.visibility import assess

# The model is asked for exactly this shape.  Keeping the schema tiny is
# deliberate: every extra field is another thing a small model can get wrong,
# and each one would need its own failure branch below.
_SCHEMA_HINT = '{"matches": true, "confident": true, "reason": "short phrase"}'

_SYSTEM_PROMPT = (
    "You are a product verification check in a retail self-checkout system. "
    "You are shown ONE photo of an item a shopper just placed in their cart, "
    "and told which product the barcode scanner says it should be. "
    "Answer only whether the photo shows that product.\n\n"
    "Reply with JSON only, no prose, in exactly this form:\n"
    f"{_SCHEMA_HINT}\n\n"
    "matches   = true if the photo shows the stated product, false otherwise.\n"
    "confident = true only if the photo is clear enough to be sure. If the "
    "image is blurry, dark, mostly obscured, or you are unsure for any "
    "reason, set confident to false.\n"
    "reason    = a brief phrase explaining what you saw.\n\n"
    "It is much better to say confident=false than to guess. A wrong 'yes' "
    "lets a theft through; a wrong 'no' wrongly accuses a shopper."
)


@dataclass
class AICallStats:
    """
    What one call actually cost and took.

    Measured, not estimated — the whole point of recording this is that the
    per-image token count and latency of a VLM are exactly the numbers this
    project has been guessing at.  compare_backends.py aggregates these.
    """
    ok: bool
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error: str = ""
    raw_reply: str = ""


def _encode_crop(crop: np.ndarray, max_side: int = AI_BACKEND_MAX_SIDE) -> str:
    """
    Downscale a crop and return it as a base64 data URI (JPEG).

    Downscaling is for transfer speed, not cost: providers bill per image
    largely independent of resolution.  max_side keeps a product label legible
    while keeping the payload small enough to matter over shop WiFi.
    """
    h, w = crop.shape[:2]
    longest = max(h, w)
    if longest > max_side:
        scale = max_side / float(longest)
        crop = cv2.resize(crop, (max(1, int(w * scale)), max(1, int(h * scale))),
                          interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise ValueError("could not JPEG-encode crop")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _best_crop(crops: List[np.ndarray]) -> Optional[np.ndarray]:
    """
    Pick the single clearest crop to send.

    Chosen by the EDGE ENERGY that ml.visibility.assess already computes — the
    standard focus/detail measure — so the sharpest, most detailed view wins.

    Note on why not the appearance score: the verifier also produces a per-crop
    MobileNet similarity, and picking the argmax of THAT would mean the local
    model chooses the evidence the AI gets to see.  Since the entire purpose of
    this class is to be compared against that model, letting it curate the
    input would quietly bias the comparison.  Sharpness is independent of both.
    """
    best, best_score = None, -1.0
    for c in crops or []:
        v = assess(c)
        if not v.usable:
            continue
        if v.edges > best_score:
            best, best_score = c, v.edges
    return best


class VLMBackend:
    """
    Verifies a crop against the expected SKU by asking a vision model.

    Parameters
    ----------
    model : str
        Model id.  Cloud e.g. "inclusionai/ling-3.0-flash-vl:free" or
        "z-ai/glm-5.3-flash"; local Ollama e.g. "minicpm-v4.6:1b".
    base_url : str
        OpenAI-compatible endpoint root (no trailing /chat/completions).
    api_key : str, optional
        Defaults to $OPENROUTER_API_KEY, else $OPENAI_API_KEY.  Ollama needs
        none, so a missing key is only fatal for a remote host.
    sku_labels : dict {sku: human readable name}, optional
        A model cannot recognise "sku_a" — it needs "Lay's Classic 52g".  Any
        SKU without a label falls back to the raw id with underscores spaced
        out, which is better than nothing but worth populating properly.
    """

    def __init__(
        self,
        model: str = AI_BACKEND_MODEL,
        base_url: str = AI_BACKEND_BASE_URL,
        api_key: Optional[str] = None,
        timeout_sec: float = AI_BACKEND_TIMEOUT_SEC,
        sku_labels: Optional[dict] = None,
        name: str = "ai",
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.sku_labels = sku_labels or {}
        self.api_key = (api_key
                        or os.environ.get("OPENROUTER_API_KEY")
                        or os.environ.get("OPENAI_API_KEY")
                        or "")
        # Every call's stats, for the comparison table's cost/latency columns.
        self.stats: List[AICallStats] = []

    # ── the backend interface ─────────────────────────────────────

    def verify(self, expected_sku: str, crops: List[np.ndarray],
               follower_broken: bool = False) -> VerdictResult:
        """
        Judge whether `crops` show `expected_sku`, via the vision model.

        Mirrors ProductVerifier.verify()'s guard order exactly so the two
        backends agree on WHICH cases are even judgeable, and only differ on
        the judgement itself.  (If one backend answered RETRY where the other
        answered MATCH purely because of a different usable-crop rule, the
        comparison would be measuring the guards, not the models.)
        """
        # Broken custody -> RETRY, regardless of how good a crop looks.  Same
        # rule as the local path: a crop we cannot attribute to the scanned
        # item proves nothing about the scanned item.
        if follower_broken:
            return self._result(Verdict.RETRY, 0,
                                "Lost track of the item during handling. "
                                "Please re-scan.", expected_sku)

        usable = [c for c in (crops or []) if assess(c).usable]
        if len(usable) < VERIFY_MIN_USABLE_FRAMES:
            return self._result(
                Verdict.RETRY, len(usable),
                f"Only {len(usable)} clear view(s) of the item "
                f"(need {VERIFY_MIN_USABLE_FRAMES}). Please re-present it.",
                expected_sku)

        crop = _best_crop(usable)
        if crop is None:
            return self._result(Verdict.RETRY, len(usable),
                                "No usable view of the item.", expected_sku)

        advice, stats = self._ask(expected_sku, crop)
        self.stats.append(stats)

        # Any transport or parse failure -> RETRY.  Explicitly NOT MISMATCH:
        # a dead network is not evidence against the shopper, and it must not
        # be recorded as the model having judged the item.
        if advice is None:
            return self._result(Verdict.RETRY, len(usable),
                                f"AI check unavailable ({stats.error}). "
                                f"Please re-scan.", expected_sku)

        matches, confident, reason = advice
        if matches and confident:
            verdict = Verdict.MATCH
        elif matches and not confident:
            # Right product, but the model would not commit.  That is the
            # definition of SUSPECT: plausible, unproven, do not accept.
            verdict = Verdict.SUSPECT
        else:
            # not matches.  A confident "no" is a MISMATCH; a hesitant "no"
            # is only enough for SUSPECT, since an unsure negative should not
            # accuse a shopper outright.
            verdict = Verdict.MISMATCH if confident else Verdict.SUSPECT

        return self._result(verdict, len(usable), reason, expected_sku,
                            latency_ms=stats.latency_ms,
                            tokens=stats.total_tokens)

    # ── the HTTP call ─────────────────────────────────────────────

    def _ask(self, expected_sku: str, crop: np.ndarray
             ) -> Tuple[Optional[Tuple[bool, bool, str]], AICallStats]:
        """
        One request.  Returns ((matches, confident, reason), stats) on success
        or (None, stats) on ANY failure, with the reason in stats.error.

        This method deliberately swallows every exception: it is called from
        the verification path, and an unhandled error there is a crash in the
        theft-prevention component.  A crash is strictly worse than a RETRY.
        """
        t0 = time.perf_counter()

        def fail(msg: str, raw: str = "") -> Tuple[None, AICallStats]:
            return None, AICallStats(
                ok=False, latency_ms=(time.perf_counter() - t0) * 1000.0,
                error=msg, raw_reply=raw)

        # A remote endpoint with no key cannot work; say so plainly rather
        # than sending a request guaranteed to 401.  Localhost (Ollama)
        # legitimately needs no key.
        is_local = ("localhost" in self.base_url or "127.0.0.1" in self.base_url)
        if not self.api_key and not is_local:
            return fail("no API key (set OPENROUTER_API_KEY)")

        try:
            import requests
        except ImportError:
            return fail("requests not installed")

        try:
            data_uri = _encode_crop(crop)
        except Exception as e:
            return fail(f"encode failed: {e}")

        label = self.sku_labels.get(expected_sku) or expected_sku.replace("_", " ")
        user_text = (f"The barcode scanner says this item is: {label}\n"
                     f"Does the photo show that product?")

        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": [
                    # Image before text: several small VLMs attend better this
                    # way, and Ollama's own docs recommend it.
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": user_text},
                ]},
            ],
            # Ask for machine-readable output.  Not every model honours this,
            # which is why _parse below also copes with prose-wrapped JSON.
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = requests.post(f"{self.base_url}/chat/completions",
                                 headers=headers, json=payload,
                                 timeout=self.timeout_sec)
        except Exception as e:
            # Covers timeout, DNS failure, refused connection, WiFi drop.
            return fail(f"{type(e).__name__}: {e}")

        if resp.status_code != 200:
            return fail(f"HTTP {resp.status_code}: {resp.text[:160]}")

        try:
            body = resp.json()
            reply = body["choices"][0]["message"]["content"]
            usage = body.get("usage") or {}
        except Exception as e:
            return fail(f"bad response shape: {e}", resp.text[:200])

        parsed = _parse(reply)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        stats = AICallStats(
            ok=parsed is not None,
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            error="" if parsed is not None else "unparseable reply",
            raw_reply=(reply or "")[:200],
        )
        return parsed, stats

    # ── result construction ───────────────────────────────────────

    def _result(self, verdict: str, usable: int, reason: str, sku: str,
                latency_ms: float = 0.0, tokens: int = 0) -> VerdictResult:
        """
        Build a VerdictResult in the same shape the local path returns.

        The numeric score fields are left at 0.0 on purpose: this backend does
        not compute an appearance cosine or a colour histogram, and inventing
        plausible-looking numbers for them would make the comparison table lie
        about what was actually measured.  The verdict and the reason are the
        real output; latency and tokens are recorded separately.
        """
        r = VerdictResult(
            verdict=verdict,
            appearance_score=0.0,
            colour_score=0.0,
            appearance_pass_frac=0.0,
            colour_pass_frac=0.0,
            usable_crops=usable,
            reason=reason,
            expected_sku=sku,
        )
        # Extra measured fields, attached dynamically so VerdictResult stays
        # the plain shared shape both backends return.
        r.ai_latency_ms = latency_ms   # type: ignore[attr-defined]
        r.ai_tokens = tokens           # type: ignore[attr-defined]
        return r


def _parse(reply: str) -> Optional[Tuple[bool, bool, str]]:
    """
    Pull (matches, confident, reason) out of a model reply.

    Tolerant of the two things small models reliably do wrong — wrapping JSON
    in ```code fences``` and adding a sentence before it — but NOT tolerant
    about the fields themselves.  A reply missing `matches` or `confident`, or
    carrying a non-boolean in either, returns None (-> RETRY).  Guessing a
    default for a missing field is how a broken reply silently becomes an
    accept, so there is no default.
    """
    if not reply or not reply.strip():
        return None

    text = reply.strip()
    if text.startswith("```"):
        # ```json\n{...}\n```  ->  {...}
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]

    obj = None
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        # Fall back to the first {...} block in the text.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(text[start:end + 1])
            except (ValueError, TypeError):
                return None

    if not isinstance(obj, dict):
        return None
    if not isinstance(obj.get("matches"), bool):
        return None
    if not isinstance(obj.get("confident"), bool):
        return None

    reason = obj.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "(no reason given)"
    return bool(obj["matches"]), bool(obj["confident"]), reason.strip()[:200]
