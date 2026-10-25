"""Tests for the step-2 real-pages data model."""
from book_pages import BookPages, Side


def test_defaults_are_blank():
    b = BookPages(3)
    assert b.page_count == 3 and b.sheet_count == 3
    assert len(b.sides) == 6
    assert all(s.kind == 'blank' for s in b.sides)


def test_front_back_mapping():
    b = BookPages(2)
    b.set(0, front=Side('text', text='page 1'), back=Side('image', image='a.png'))
    b.set(1, front=Side('text', text='page 3'))
    assert b.front(0).kind == 'text' and b.front(0).text == 'page 1'
    assert b.back(0).kind == 'image' and b.back(0).image == 'a.png'
    assert b.front(1).text == 'page 3'
    assert b.back(1).kind == 'blank'


def test_roundtrip():
    b = BookPages(4)
    b.set(0, front=Side('image', image='c.png'))
    b.set(3, back=Side('text', text='last page'))
    b2 = BookPages.from_dict(b.to_dict())
    assert b2.page_count == 4
    assert b2.sides == b.sides


def test_roundtrip_empty_dict_gives_default():
    b = BookPages.from_dict({})
    assert b.page_count == 50 and b.sheet_count == 50


def test_bad_page_count_raises():
    for bad in (0, -3):
        try:
            BookPages(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'BookPages({bad}) should raise ValueError')


def test_bad_side_kind_raises():
    try:
        Side('video')
    except ValueError:
        pass
    else:
        raise AssertionError("Side('video') should raise ValueError")


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
