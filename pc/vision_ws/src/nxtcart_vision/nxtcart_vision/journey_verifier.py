"""Do not let early matching views outvote a substitution at rest."""
from ml.verifier import VerdictResult


def verify_journey(backend, sku, crops):
    # Three independent windows need three clear physical frames each. Captures
    # contain six earlier journey views followed by three observed rest views,
    # supplied in chronological order by CapturePipeline.
    if len(crops) < 9:
        return VerdictResult('RETRY', 0., 0., 0., 0., len(crops),
            'Need clear beginning, middle and resting views; remove this unit and scan again', sku)
    results = []
    for index, label in enumerate(('beginning', 'middle', 'rest')):
        window = crops[index*len(crops)//3:(index+1)*len(crops)//3]
        result = backend.verify(sku, window)
        if result.verdict != 'MATCH':
            result.reason = f'{label.capitalize()} of journey: {result.reason}'
            return result
        if label == 'rest' and result.joint_pass_frac < 1.0:
            result.verdict = 'SUSPECT'
            result.reason = 'Resting views are inconsistent with the scanned product; remove and scan again'
            return result
        results.append(result)
    return VerdictResult('MATCH', min(r.appearance_score for r in results),
        min(r.colour_score for r in results), min(r.appearance_pass_frac for r in results),
        min(r.colour_pass_frac for r in results), sum(r.usable_crops for r in results),
        'Product matches independently at beginning, middle and rest', sku,
        joint_pass_frac=min(r.joint_pass_frac for r in results))
