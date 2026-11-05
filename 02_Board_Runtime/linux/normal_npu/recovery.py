"""Bounded transport/measurement recovery; never changes data/model qualification."""
import time

WAIT_SECONDS = 3.0
MAX_EXTRA_CAPTURE_ATTEMPTS = 2
TRANSIENT_INPUT = frozenset(('NO_NEW_REAL_FRAME', 'WAIT_FOR_REAL_FRAME',
    'SENSOR_OR_WINDOW_INVALID', 'SAMPLE_RATE_INVALID', 'FRAME_STALE',
    'COLLECTOR_STALE', 'PROCESS_SENSOR_INVALID', 'INDEPENDENT_ICM_PAIR_INVALID',
    'TEMPERATURE_STALE', 'FG_INPUT_INVALID'))
RETRY_CAPTURE = frozenset(('NO_FRESH_FRAMES', 'COLLECTOR_STALE', 'COLLECTOR_GAP',
    'INDEPENDENT_WINDOW_LOSS_BUDGET',
    'INSUFFICIENT_COMPLETE_WINDOWS','CALIBRATION_TRANSIENT_INPUT_COVERAGE')) | (TRANSIENT_INPUT - {'NO_NEW_REAL_FRAME', 'WAIT_FOR_REAL_FRAME'})

def description(reason):
    if reason == 'CAPTURE_QUEUE_OVERFLOW': return '采集队列溢出，需检查并重新确认当前工况'
    if reason in ('NO_NEW_REAL_FRAME', 'WAIT_FOR_REAL_FRAME'): return '等待下一帧完整实测数据'
    if reason in ('NO_FRESH_FRAMES', 'FRAME_STALE', 'COLLECTOR_STALE'): return '等待采集数据恢复更新'
    if reason in ('COLLECTOR_GAP', 'INDEPENDENT_WINDOW_LOSS_BUDGET'): return '本段采集有丢帧，重新采集本段'
    if reason == 'INSUFFICIENT_COMPLETE_WINDOWS': return '本段完整样本不足，重新采集本段'
    if reason == 'CALIBRATION_TRANSIENT_INPUT_COVERAGE': return '校验段有短时输入扰动，重新采集校验段；独立测试段尚未开始'
    return '等待传感器和采样窗口恢复稳定'

def await_stable(probe, publish, clock=None, sleep=None):
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    started=clock();deadline=started+WAIT_SECONDS;waiting=False
    try:
        while True:
            try:
                value=probe()
                return value
            except ValueError as error:
                reason=str(error)
                if reason not in TRANSIENT_INPUT: raise
                if clock()>=deadline: raise
                if not waiting:
                    publish(dict(waiting_stable=True,display_state='WAITING_STABLE',
                        waiting_reason=description(reason),waiting_reason_code=reason,
                        waiting_since=started,waiting_deadline=deadline))
                    waiting=True
                sleep(min(.1,max(0,deadline-clock())))
    finally:
        if waiting: publish(dict(waiting_stable=False))
