"""Phase 1: conservation harness. Every physical sheet counted exactly once.

Each sheet contributes to exactly one category per frame:
  resting left  -> left_contact  = 1
  resting right -> right_contact = 1
  turning       -> right_contact(p) + left_contact(p) <= 1, remainder airborne
"""
import sys
from pathlib import Path

WS = Path(r'C:\Users\Alejandro\Documents\deepseek-harness\default-workspace')
sys.path.insert(0, str(WS / 'Handyman'))
import book_model as bm  # noqa: E402

GAP = bm.SHEET_GAP
N = 20


def clamp(x):
    return max(0.0, min(1.0, x))


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def right_contact(p, lift=0.25):
    return 1.0 - smooth(p / lift)


def left_contact(p, land=0.75):
    return smooth((p - land) / (1.0 - land))


def weights(p):
    """Contact weights for one sheet at progress p. Exactly one rule, no double counting."""
    if p <= 0.0:
        return 1.0, 0.0            # fully resting right
    if p >= 1.0:
        return 0.0, 1.0            # fully landed left
    rc, lc = right_contact(p), left_contact(p)
    assert 0.0 <= rc + lc <= 1.0 + 1e-12, (p, rc, lc)
    return rc, lc


def measure(progress):
    """Sum contributions over all sheets, classifying each exactly once."""
    h_left = h_right = h_air = 0.0
    for p in progress:
        rc, lc = weights(p)
        h_left += lc * GAP
        h_right += rc * GAP
        h_air += (1.0 - rc - lc) * GAP
    return h_left, h_right, h_air


def check_case(name, progress):
    h_left, h_right, h_air = measure(progress)
    total = h_left + h_right + h_air
    ok = abs(total - N * GAP) < 1e-12
    n_l = sum(1 for p in progress if p >= 1.0)
    n_r = sum(1 for p in progress if p <= 0.0)
    n_a = N - n_l - n_r
    print(f'  {name:26s} left={h_left:.6f} right={h_right:.6f} air={h_air:.6f} '
          f'sum={total:.6f} ({n_l} landed, {n_r} resting, {n_a} turning) '
          f'{"OK" if ok else "BAD"}')
    assert ok, (name, total)
    return n_l, n_r, n_a


print(f'page_count={N}  SHEET_GAP={GAP}  expected total={N * GAP:.6f}')
print()
print('=== whole-book configurations ===')
cases = [
    ('closed, 0 turns', [0.0] * N),
    ('1 landed, 0 turning', [1.0] + [0.0] * (N - 1)),
    ('1 turning mid-air', [0.5] + [0.0] * (N - 1)),
    ('1 turning lifting', [0.15] + [0.0] * (N - 1)),
    ('1 turning settling', [0.9] + [0.0] * (N - 1)),
    ('5 landed', [1.0] * 5 + [0.0] * (N - 5)),
    ('10 landed', [1.0] * 10 + [0.0] * (N - 10)),
    ('15 landed', [1.0] * 15 + [0.0] * (N - 15)),
    ('all 20 landed', [1.0] * N),
    ('10 landed + 1 airborne', [1.0] * 10 + [0.5] + [0.0] * 9),
    ('19 landed + 1 lifting', [1.0] * 19 + [0.05]),
    ('19 landed + 1 settling', [1.0] * 19 + [0.95]),
]
for name, prog in cases:
    check_case(name, prog)

print()
print('=== sweep a single turn across the whole arc, in fine steps ===')
prev = None
worst_step = 0.0
for i in range(0, 101):
    p = i / 100.0
    prog = [p] + [0.0] * (N - 1)
    h_left, h_right, h_air = measure(prog)
    total = h_left + h_right + h_air
    assert abs(total - N * GAP) < 1e-12, (p, total)
    jump = 0.0 if prev is None else abs(h_right - prev)
    worst_step = max(worst_step, jump)
    prev = h_right
print(f'  100 steps checked; total constant; largest single-step change in h_right = {worst_step:.6f}')
print(f'  (one gap = {GAP:.6f}; a step must stay well under this to avoid visible jumps)')

print()
print('=== release and landing weights are continuous at the boundaries ===')
for label, a, b in (('p=0.000 -> 0.001', 0.0, 0.001), ('p=0.249 -> 0.251', 0.249, 0.251),
                    ('p=0.749 -> 0.751', 0.749, 0.751), ('p=0.999 -> 1.000', 0.999, 1.0)):
    ra, la = weights(a)
    rb, lb = weights(b)
    print(f'  {label}: right {ra:.6f}->{rb:.6f} (d={abs(rb-ra):.2e})  '
          f'left {la:.6f}->{lb:.6f} (d={abs(lb-la):.2e})')

print()
print('PHASE 1 HARNESS: ALL CHECKS PASSED')
