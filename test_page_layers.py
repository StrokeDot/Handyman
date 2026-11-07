"""Pictures on pages ("layers") with Ink on the page, and new book shapes."""
import numpy as np
from PIL import Image, ImageDraw

import page_layers as PL
from journal_dialog import sizes_for


def _sketch(path, size=(400, 300)):
    """A dark line drawing on an off-white 'scanned paper' background."""
    img = Image.new('RGB', size, (236, 230, 218))
    d = ImageDraw.Draw(img)
    d.line((20, size[1] // 2, size[0] - 20, size[1] // 2), fill=(30, 25, 20), width=8)
    img.save(path)
    return str(path)


def test_ink_makes_the_pictures_paper_see_through_and_keeps_the_lines(tmp_path):
    layer = PL.new_layer(_sketch(tmp_path / 's.png'), ink_edges='No fading')
    pic = np.asarray(PL.layer_picture(layer))
    assert pic[10, 200, 3] < 10              # its paper: gone
    assert pic[150, 200, 3] > 200            # its line: ink
    assert tuple(pic[150, 200, :3]) == PL.INK_COLOURS['Dark grey (like printed text)']


def test_ink_off_keeps_the_picture_as_it_is(tmp_path):
    layer = PL.new_layer(_sketch(tmp_path / 's.png'), ink_on=False, ink_edges='No fading')
    pic = np.asarray(PL.layer_picture(layer))
    assert pic[10, 200, 3] == 255 and tuple(pic[10, 200, :3]) == (236, 230, 218)


def test_soft_and_oval_edges_fade_to_nothing_at_the_border(tmp_path):
    for edges in ('Soft edges', 'Oval fade'):
        layer = PL.new_layer(_sketch(tmp_path / 's.png'), ink_on=False, ink_edges=edges, ink_edge_size=20)
        pic = np.asarray(PL.layer_picture(layer))
        assert pic[150, 0, 3] == 0 and pic[150, 200, 3] == 255


def test_layer_lands_where_it_is_placed_on_the_page(tmp_path):
    layer = PL.new_layer(_sketch(tmp_path / 's.png'), x=0.25, y=0.75, w=0.4, ink_edges='No fading')
    page = np.asarray(PL.compose(None, [layer], (1000, 1400)))
    assert page[1050, 250, 3] > 200          # the line, centred at (0.25, 0.75) of the page
    assert page[350, 750, 3] == 0            # elsewhere the page stays see-through (paper shows)
    corners = PL.layer_corners(layer, (400, 300), (1000, 1400))
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    assert abs(min(xs) - 50) < 1 and abs(max(xs) - 450) < 1 and abs(max(ys) - min(ys) - 300) < 1


def test_a_picture_partly_off_the_page_is_cut_at_the_edge(tmp_path):
    layer = PL.new_layer(_sketch(tmp_path / 's.png'), x=0.0, y=0.5, w=0.5, ink_edges='No fading')
    page = PL.compose(None, [layer], (600, 800))
    assert page.size == (600, 800)
    assert np.asarray(page)[400, 50, 3] > 200


def test_composed_file_is_reused_until_something_changes(tmp_path):
    src = _sketch(tmp_path / 's.png')
    layers = [PL.new_layer(src)]
    a = PL.compose_to_file(None, layers, (300, 420), tmp_path / 'out')
    assert PL.compose_to_file(None, layers, (300, 420), tmp_path / 'out') == a
    layers[0]['ink_colour'] = 'Sepia'
    assert PL.compose_to_file(None, layers, (300, 420), tmp_path / 'out') != a


def test_new_shape_sizes_keep_widths_and_follow_the_page_and_cover():
    sizes = {'front_exterior_image': [1080, 1602], 'spine_exterior_image': [724, 2172],
             'joint_image': [56, 1406], 'paper_odd_image': [982, 1406], 'page': [982, 1406]}
    assert sizes_for(sizes, 1.4318, 1.4318) == sizes
    wide = sizes_for(sizes, 1.4318, 15 / 21)
    assert wide['page'] == [982, round(1406 * (15 / 21) / 1.4318)]
    assert wide['joint_image'][1] == wide['page'][1]
    assert wide['front_exterior_image'] == [1080, round(1602 * (15 / 21 + 0.17) / (1.4318 + 0.17))]


def test_a_smaller_book_looks_smaller_in_the_picture_and_the_journal_is_unchanged():
    import camera_fit as cf
    import journal_geom as G
    cam = dict(cf.PRESETS['Eye level (reading at a desk)'], zoom=1.0, move='none')
    G.configure(10, 1.4318)
    base = G.camera(cam, 0.5, 16 / 9)
    same = G.camera(cam, 0.5, 16 / 9, G.real_size({'page_size_cm': [15.0, 21.48]}))
    assert abs(np.linalg.norm(base[0]) - np.linalg.norm(same[0])) < 2e-3
    G.configure(10, 7.0 / 5.5)
    fit = G.camera(cam, 0.5, 16 / 9)
    small = G.camera(cam, 0.5, 16 / 9, G.real_size({'page_size_cm': [5.5, 7.0]}))
    assert np.linalg.norm(small[0]) > 2 * np.linalg.norm(fit[0])     # camera much farther away
    big = G.camera(cam, 0.5, 16 / 9, G.real_size({'page_size_cm': [30.0, 40.0]}))
    assert abs(np.linalg.norm(big[0]) - np.linalg.norm(fit[0])) < 1e-6   # a big book stays whole
    G.configure(10, 1.4318)


def test_a_picture_across_two_pages_is_cut_down_the_middle(tmp_path):
    src = _sketch(tmp_path / 's.png', (800, 300))
    layer = PL.new_layer(src, spread=True, x=0.5, y=0.5, w=0.9, ink_edges='No fading')
    left, right = PL.compose_spread(None, None, [layer], (500, 700))
    l, r = np.asarray(left), np.asarray(right)
    assert l.shape == r.shape == (700, 500, 4)
    assert l[350, 200, 3] > 200 and r[350, 300, 3] > 200        # the line runs over both pages
    assert l[350, 499, 3] < 70 and r[350, 0, 3] < 70            # and fades at the spine (the gutter)
    own, spread = PL.split([PL.new_layer(src), layer])
    assert len(own) == 1 and spread == [layer]


def test_fit_inside_the_margins(tmp_path):
    layer = PL.new_layer(_sketch(tmp_path / 's.png', (400, 300)))
    PL.fit_in_margins(layer, (400, 300), (1000, 1400), 1000, 0.1)
    assert abs(layer['w'] - 0.8) < 1e-6 and layer['x'] == 0.5 and layer['y'] == 0.5
    PL.fit_in_margins(layer, (400, 300), (2000, 1400), 1000, 0.1)     # across two pages: limited by height
    assert abs(layer['w'] * 2000 - 1200 * 4 / 3) < 1


def test_the_cover_can_be_sized_apart_from_the_pages_but_always_covers_them():
    import journal_geom as G
    G.configure(10, 1.4318)
    assert abs(G.WC - 1.08) < 1e-9 and abs(G.HC - (1.4318 + 0.17)) < 1e-9
    G.configure(10, 1.4318, cover=G.cover_of({'page_size_cm': [15, 21.48], 'cover_size_cm': [19, 26]}))
    assert abs(G.WC - 19 / 15) < 1e-9 and abs(G.HC - 26 / 15) < 1e-9
    assert G.COVER_MARGIN > (G.HC - G.H) / 2
    G.configure(10, 1.4318, cover=(0.5, 0.5))                         # too small: grows to cover the pages
    assert G.WC >= G.W - G.XB and G.HC >= G.H
    G.configure(10, 1.4318)


def test_zoom_style_lens_keeps_the_camera_closer_moves_it():
    import camera_fit as cf
    import journal_geom as G
    G.configure(10, 1.4318)
    base = dict(cf.PRESETS['Eye level (reading at a desk)'], zoom=1.0, move='none')
    c1 = G.camera(dict(base), 0.5, 16 / 9)
    lens = G.camera(dict(base, zoom=2.0), 0.5, 16 / 9)
    closer = G.camera(dict(base, zoom=2.0, zoom_mode='closer'), 0.5, 16 / 9)
    assert np.allclose(lens[0], c1[0]) and abs(lens[4] - 2 * c1[4]) < 1e-9          # same spot, longer lens
    assert np.linalg.norm(closer[0]) < np.linalg.norm(c1[0]) and abs(closer[4] - c1[4]) < 1e-9


def test_cover_corner_is_read_from_the_art_and_transparent_pixels_are_filled(tmp_path):
    import cover_shape as C
    w, h, r = 400, 600, 40
    yy, xx = np.mgrid[0:h, 0:w] + 0.5
    a = np.full((h, w), 255, np.uint8)
    for cy in (r, h - r):                                   # round the two fore-edge corners
        near = (xx > w - r) & (np.abs(yy - cy) <= r) & ((yy < r) | (yy > h - r))
        a[near & ((xx - (w - r)) ** 2 + (yy - cy) ** 2 > r * r)] = 0
    rgba = np.dstack([np.full((h, w), 30), np.full((h, w), 40), np.full((h, w), 120), a]).astype(np.uint8)
    img = Image.fromarray(rgba, 'RGBA')
    p = tmp_path / 'cover.png'
    img.save(p)
    share = C.corner_radius(str(p))
    assert abs(share * w - r) < 4                           # about the radius drawn
    f = Image.open(C.filled(str(p), tmp_path / 'out')).convert('RGBA')
    assert f.getpixel((w - 1, 0))[3] == 255 and f.getpixel((w - 1, 0))[:3] == (30, 40, 120)
    opaque = tmp_path / 'plain.png'
    Image.new('RGB', (100, 150), (1, 2, 3)).save(opaque)
    assert abs(C.corner_radius(str(opaque)) - C.DEFAULT_CORNER) < 1e-12
    assert C.filled(str(opaque), tmp_path / 'out') == str(opaque)
