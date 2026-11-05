"""Bounded calibration-only tolerance for harmless Alnpu vibration rounding.

The original three-count gate remains in force for the independent test and
the single-feature process outputs. Four counts on a calibration vibration
output require the original and native decisions to agree with <=0.05 change
in the normalized score. No live anomaly threshold or score is altered here.
"""
import math


def _finite(x):
    return type(x) in (int,float) and math.isfinite(x)


def review_extended_rows(report):
    maximum=report.get('max_quantized_error')
    if not _finite(maximum) or not 0<=maximum<=4:
        raise ValueError('Native output difference exceeds numerical limit')
    if maximum<=3:
        return dict(schema='cabinet-normal-calibration-rounding-v1',extended_rows=0,limit=3)
    rows=report.get('rows')
    if type(rows) is not list or len(rows)!=128 or report.get('vectors')!=128:
        raise ValueError('Full 128-vector numerical evidence required')
    extended=[]
    observed=0
    for row in rows:
        actual=row.get('output_u8');expected=row.get('reference_output_u8')
        if (type(actual) is not list or type(expected) is not list or len(actual)!=39 or len(expected)!=39
                or any(type(v) is not int or not 0<=v<=255 for v in actual+expected)):
            raise ValueError('Pinned uint8 reference output evidence missing')
        differences=[abs(a-b) for a,b in zip(actual,expected)]
        error=max(differences);observed=max(observed,error)
        if error!=row.get('max_quantized_error') or error>4:
            raise ValueError('Reported numerical difference does not match outputs')
        if error<=3:
            continue
        if row.get('split')!='calibration' or max(differences[35:])>3:
            raise ValueError('Four-count tolerance is calibration vibration only')
        expected_state=row.get('reference_state');expected_score=row.get('reference_score');actual_score=row.get('score')
        if (expected_state not in ('BASELINE_MATCH','BASELINE_DEVIATION') or row.get('state')!=expected_state
                or not _finite(expected_score) or not _finite(actual_score)
                or expected_score<0 or actual_score<0 or abs(expected_score-actual_score)>.05
                or (expected_score<=1)!=(expected_state=='BASELINE_MATCH')
                or (actual_score<=1)!=(row['state']=='BASELINE_MATCH')):
            raise ValueError('Extended rounding changes the normal decision or score materially')
        extended.append(dict(split='calibration',index=row.get('index'),
                             feature_indices=[i for i,e in enumerate(differences) if e>3],
                             score_delta=abs(actual_score-expected_score)))
    if observed!=maximum or not extended:
        raise ValueError('Maximum numerical difference is not supported by vectors')
    return dict(schema='cabinet-normal-calibration-rounding-v1',extended_rows=len(extended),
                limit=4,independent_test_limit=3,process_output_limit=3,
                maximum_score_delta=.05,decisions_preserved=True,rows=extended)
