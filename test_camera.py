"""Camera framing checks (no Blender)."""
import numpy as np
import camera_fit as cf

PTS = cf.book_points(1.0, 1.4, 0.05, 0.105)
TARGET = (0, 0, 0.105)
ASPECT = 16 / 9


def settings(name, **kw):
    s = dict(cf.PRESETS[name], zoom=1.0, move='none', shift_x=0, shift_y=0)
    s.update(kw)
    return s


def test_every_preset_fits_the_whole_book():
    for name in cf.PRESETS:
        s = settings(name)
        cam, r, u, f, lens = cf.shot(s, 0.0, TARGET, 2.1, 1.5, PTS, ASPECT)
        x, y, depth = cf.project(PTS, cam, r, u, f, lens, ASPECT)
        assert depth.min() > 0, name
        assert np.abs(x).max() <= 1.251 and np.abs(y).max() <= 1.251, name    # rising page mostly inside
        bx, by = np.abs(x[:cf.BOOK_CORNERS]).max(), np.abs(y[:cf.BOOK_CORNERS]).max()
        assert max(bx, by) <= 0.901 and max(bx, by) > 0.7, name               # book big, but inside


def test_camera_axes_are_a_proper_rotation():
    for name in cf.PRESETS:
        cam, r, u, f, _ = cf.shot(settings(name, roll=7), 0.3, TARGET, 2.1, 1.5, PTS, ASPECT)
        m = np.array(cf.matrix_rows(cam, r, u, f))[:3, :3]
        assert np.allclose(m.T @ m, np.eye(3), atol=1e-9)
        assert np.isclose(np.linalg.det(m), 1.0)


def test_eye_level_sees_near_edge_bigger_than_far_edge():
    cam, r, u, f, lens = cf.shot(settings('Eye level (reading at a desk)', roll=0), 0, TARGET, 2.1, 1.5, PTS, ASPECT)
    near = np.array([[-1.05, -0.75, 0], [1.05, -0.75, 0]])
    far = np.array([[-1.05, 0.75, 0], [1.05, 0.75, 0]])
    xn = cf.project(near, cam, r, u, f, lens, ASPECT)[0]
    xf = cf.project(far, cam, r, u, f, lens, ASPECT)[0]
    assert (xn[1] - xn[0]) > (xf[1] - xf[0]) * 1.1   # perspective: a trapezoid, like at a desk
    yn = cf.project(near, cam, r, u, f, lens, ASPECT)[1]
    assert yn.mean() < 0                                   # the near edge is at the bottom


def test_moves():
    s = settings('Angled', move='push')
    d0 = np.linalg.norm(cf.shot(s, 0, TARGET, 2.1, 1.5, PTS, ASPECT)[0] - TARGET)
    d1 = np.linalg.norm(cf.shot(s, 1, TARGET, 2.1, 1.5, PTS, ASPECT)[0] - TARGET)
    assert d1 < d0 * 0.9
    s = settings('Angled', move='drift')
    c0 = cf.shot(s, 0, TARGET, 2.1, 1.5, PTS, ASPECT)[0]
    c1 = cf.shot(s, 1, TARGET, 2.1, 1.5, PTS, ASPECT)[0]
    assert c0[0] < 0 < c1[0]


def test_roll_tilts_the_picture():
    a = cf.shot(settings('Angled', roll=0), 0, TARGET, 2.1, 1.5, PTS, ASPECT)
    b = cf.shot(settings('Angled', roll=10), 0, TARGET, 2.1, 1.5, PTS, ASPECT)
    assert np.allclose(a[3], b[3]) and not np.allclose(a[1], b[1])  # same aim, rotated picture


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
