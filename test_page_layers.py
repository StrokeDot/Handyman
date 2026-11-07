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
