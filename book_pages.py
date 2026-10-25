"""The book's real pages — step 2 data model (pure data, no Qt / no Blender).

A book has ``page_count`` sheets. Every sheet is a real sheet with a front and a back side,
and each side holds an image, typed text, or blank paper. The covers are separate (handled
later). This is saved in the project file and shared by the live view and the Blender export.

Reading order: sheet 0 is the first sheet just inside the cover.
  sheet 0 front = page 1, sheet 0 back = page 2, sheet 1 front = page 3, ...
so the side index is ``2 * sheet`` (front) and ``2 * sheet + 1`` (back).
"""


class Side:
    """One side of a sheet: an image, typed text, or blank paper."""

    def __init__(self, kind='blank', image=None, text=''):
        if kind not in ('image', 'text', 'blank'):
            raise ValueError(f'unknown side kind: {kind!r}')
        self.kind = kind
        self.image = image        # path, for kind == 'image'
        self.text = text          # for kind == 'text'

    def to_dict(self):
        return {'kind': self.kind, 'image': self.image, 'text': self.text}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(d.get('kind', 'blank'), d.get('image'), d.get('text', ''))

    def __eq__(self, other):
        return (isinstance(other, Side) and self.kind == other.kind
                and self.image == other.image and self.text == other.text)

    def __repr__(self):
        return f'Side({self.kind!r}, image={self.image!r}, text={self.text!r})'


class BookPages:
    """``page_count`` sheets, each with a front and a back side."""

    def __init__(self, page_count=50, sides=None):
        self.page_count = int(page_count)
        if self.page_count < 1:
            raise ValueError('page_count must be at least 1')
        if sides is None:
            self.sides = [Side() for _ in range(2 * self.page_count)]
        else:
            self.sides = list(sides)
        if len(self.sides) != 2 * self.page_count:
            raise ValueError(f'expected {2 * self.page_count} sides, got {len(self.sides)}')

    @property
    def sheet_count(self):
        return self.page_count

    def front(self, sheet):
        return self.sides[2 * sheet]

    def back(self, sheet):
        return self.sides[2 * sheet + 1]

    def set(self, sheet, front=None, back=None):
        if front is not None:
            self.sides[2 * sheet] = front
        if back is not None:
            self.sides[2 * sheet + 1] = back

    def to_dict(self):
        return {'page_count': self.page_count, 'sides': [s.to_dict() for s in self.sides]}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        sides = d.get('sides')
        return cls(int(d.get('page_count', 50)),
                   None if sides is None else [Side.from_dict(x) for x in sides])
