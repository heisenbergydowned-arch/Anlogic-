"""Share the already validated HDMI values with the monitoring page."""
import math


def snapshot(observer, identity, now):
    sample = getattr(observer, 'advisory_sample', None)
    rendered = getattr(observer, 'advisory_rendered', None)
    refreshed = getattr(observer, 'advisory_refreshed_at', None)
    if not identity or not isinstance(sample, dict) or not isinstance(rendered, dict):
        return dict(available=False, fields={})
    received = sample.get('received_at')
    if (sample.get('boot') != identity or sample.get('link') != 'ONLINE'
            or any(type(v) not in (int, float) or not math.isfinite(v)
                   or not 0 <= now-v <= 1 for v in (received, refreshed))):
        return dict(available=False, fields={})
    prefixes = ('daily_current_', 'panel_nn_', 'panel_classifier_', 'panel_prob_')
    fields = {k: v for k, v in rendered.items()
              if k.startswith(prefixes) and type(v) in (str, int, float, bool)}
    for prefix in ('panel_nn_', 'panel_classifier_'):
        try:
            if now * 1000 >= float(fields.get(prefix+'deadline_ms', 0)):
                fields[prefix+'valid'] = '0'
        except (TypeError, ValueError):
            fields[prefix+'valid'] = '0'
    return dict(available=True, age_ms=round((now-received)*1000), fields=fields)
