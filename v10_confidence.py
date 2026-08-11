#!/usr/bin/env python3
"""V10 confidence model.

Confidence is a reliability score, not a win probability. It must never be
boosted simply because the independent model disagrees strongly with the
market. Reference-book depth and data quality impose hard ceilings.
"""
import math


def clamp(x, a=0.0, b=10.0):
    return max(a, min(b, x))


def num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def refs_cap(refs):
    refs = int(max(0, num(refs, 0)))
    if refs <= 0:
        return 5.4
    if refs == 1:
        return 6.0
    if refs == 2:
        return 7.5
    if refs == 3:
        return 8.8
    return 9.5


def quality_cap(quality):
    q = clamp(num(quality, 0), 0, 1)
    if q < .50:
        return 5.3
    if q < .60:
        return 6.2
    if q < .70:
        return 7.3
    if q < .80:
        return 8.4
    return 9.5


def disagreement_adjustment(p_model, p_market, refs):
    """Return a non-positive/limited adjustment for model-vs-market gap.

    Small agreement can add only a tiny reliability bonus. Large disagreement
    is penalised because it is uncertainty until validated empirically.
    """
    if p_market is None:
        return -0.20
    gap = abs(num(p_model, .5) - num(p_market, .5))
    refs = int(max(0, num(refs, 0)))
    if gap <= .025:
        return .25 if refs >= 3 else .10
    if gap <= .050:
        return .10 if refs >= 3 else 0.0
    if gap <= .080:
        return 0.0
    if gap <= .110:
        return -0.25
    if gap <= .150:
        return -0.55
    return -0.90


def confidence_v10(p_model, quality, p_market=None, refs=0):
    """Professional confidence score for V10.

    Inputs intentionally match V9's model_signal_confidence signature so the
    function can replace it safely in the integration runner.
    """
    p = clamp(num(p_model, .5), .001, .999)
    q = clamp(num(quality, 0), 0, 1)
    refs_i = int(max(0, num(refs, 0)))

    # Start conservative. Probability strength contributes, but far less than
    # in V9 because 68% from a poorly calibrated model is not "high confidence".
    score = 4.15

    # Data quality is the largest positive component.
    score += clamp((q - .45) / .45, 0, 1) * 2.05

    # Directional strength: modest contribution only.
    strength = abs(p - .5)
    score += clamp(strength / .20, 0, 1) * 1.15

    # Independent reference depth improves reliability, not direction.
    score += {0: 0.0, 1: .15, 2: .40, 3: .62}.get(min(refs_i, 3), .62)
    if refs_i >= 4:
        score += min(.28, (refs_i - 3) * .07)

    # A large disagreement can only reduce confidence until historical evidence
    # shows this type of contrarian signal is actually calibrated.
    score += disagreement_adjustment(p, p_market, refs_i)

    # Low-quality strong probabilities are a classic overconfidence pattern.
    if q < .60 and strength > .12:
        score -= .35
    if q < .50:
        score -= .25

    score = clamp(score, 4.0, 9.5)
    score = min(score, refs_cap(refs_i), quality_cap(q))
    return round(score, 2)


def confidence_diagnostics(p_model, quality, p_market=None, refs=0):
    """Small audit payload for logs/tests."""
    return {
        "score": confidence_v10(p_model, quality, p_market, refs),
        "refs_cap": refs_cap(refs),
        "quality_cap": quality_cap(quality),
        "gap": None if p_market is None else abs(num(p_model, .5) - num(p_market, .5)),
        "gap_adjustment": disagreement_adjustment(p_model, p_market, refs),
    }


def self_test():
    # Hard reference caps are non-negotiable.
    assert confidence_v10(.72, .95, .58, 0) <= 5.4
    assert confidence_v10(.72, .95, .58, 1) <= 6.0
    assert confidence_v10(.72, .95, .58, 2) <= 7.5
    assert confidence_v10(.72, .95, .58, 4) <= 9.5

    # A giant contrarian gap must NOT increase confidence versus a small gap.
    aligned = confidence_v10(.66, .88, .64, 4)
    contrarian = confidence_v10(.66, .88, .48, 4)
    assert aligned > contrarian, (aligned, contrarian)

    # Better data quality should increase confidence when everything else is equal.
    low_q = confidence_v10(.62, .55, .59, 4)
    high_q = confidence_v10(.62, .90, .59, 4)
    assert high_q > low_q, (low_q, high_q)

    # Missing market information cannot be treated as confirmation.
    missing = confidence_v10(.64, .85, None, 0)
    with_refs = confidence_v10(.64, .85, .62, 4)
    assert with_refs > missing, (missing, with_refs)

    # The exact audit example: one reference book cannot produce 9/10.
    assert confidence_v10(.68, .95, .55, 1) <= 6.0

    print("SELF-TEST V10 CONFIDENCE OK", {
        "aligned": aligned,
        "contrarian": contrarian,
        "low_quality": low_q,
        "high_quality": high_q,
        "one_ref_68pct": confidence_v10(.68, .95, .55, 1),
    })


if __name__ == "__main__":
    self_test()
