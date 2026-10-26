# Changes

## 0.6.4
- Flexible hinge: the cover board is joined to the spine by a deformable joint that stays glued to both, so the binding no longer gaps at any opening angle.
- Brown leather interior covers (pastedowns) with tooled borders, in the app and in the render.
- Replaceable artwork for the front/back exterior, front/back interior and the spine, from Book design.
- Fit / Fill / Stretch with scale and position for every cover surface and every page image, without changing the book's geometry.
- Per-page image framing: select a page and choose its Fit / Fill / scale / position.
- The live viewport and the Blender export share the same joint, framing and layout code.

## 0.6.3
- The live viewport now uses the real leather texture and a debossed tooled border, so the cover in the app matches the render.
- Fixed the visible gap at the spine while the cover is opening.

## 0.6.2
- Orbit the book to any angle, including from below and behind. The camera tilt and turn are no longer clamped.
- Move, rotate and scale the whole book as a 3D object (X/Y/Z each), with a reset. It is saved in projects and applied to Blender exports.
- Visual timeline panel: click a clip to select it, drag to reorder, trim, duplicate, delete, undo/redo, and set each clip's Speed and Smoothness.
- Shift+drag a page to turn it in the live view, so a plain drag still orbits the camera.
- Redesigned cover: a thicker, rounded leather board with a generous margin, a raised rounded spine, and a debossed tooled border.
- Pages now have real paper thickness and contact shadows (ambient occlusion) where they meet.
- The page turn settles gently as it lands instead of snapping flat.

## 0.6.1
- Drag pages in the live view to turn them like a real book ("Drag pages" toggle). A page follows the mouse and snaps forward or back when you let go.
- Smoothness control for every action (0 = linear, 100 = gentle), so the motion no longer has to be hand-keyframed.
- Record mode: a finished page drag becomes a timeline clip ("Record" toggle).
- The book now uses your leather and aged-paper photos for the cover and pages.
- The scene plays from a clip-based timeline (same look as before).

## 0.6.0
- Real pages: every page is now a real sheet with a front and a back, instead of one solid paper block.
- Page count: set how many sheets the book has (2–2000).
- Typed text on pages, alongside images and blank pages.
- Swappable cover parts: the front cover, back cover, and inside cover (endpaper) each have their own colour.
- Updates are verified against a SHA-256 checksum, and a failed update can be recovered.

## 0.5.0
- Live 3D view: the book, your pages, the cover opening and the page turns play inside the app instantly, no rendering. Play / pause, speed (0.25× to 2×), loop, and a timeline you can drag.
- Drag the live view with the mouse to move the camera; every setting change shows immediately. Blender is only needed for the final video.
- "Book opens at": opening from the beginning now swings only the cover, with the pages staying on the right (no more half of the book lifting like a slab).
- Pages on each side curve according to how thick that side is.

## 0.4.0
- Move the camera with the mouse: in "Set up the shot", drag to look around the book, right-drag to move it, mouse wheel to zoom, double-click to reset.
- Pages curve down into the spine like a real open book.
- Thicker book with a paper block that follows the page curve; page edges show stacked sheets.
- Leather: fine pebbled grain and a faint waxed sheen instead of cloudy blotches.

## 0.3.0
- New Camera panel: start from Eye level, Top-down, Angled or Low angle, then adjust tilt, turn, picture tilt, perspective, size and position.
- Live outline of the shot that updates while you drag, before any rendering.
- Slow camera moves: push-in, pull-out or sideways drift.
- The camera frames the book automatically from any angle.

## 0.2.1
- More room above the book, so a page rising mid-turn stays inside the frame.
- Unticked boxes now look clearly unticked.

## 0.2.0
- Book templates: leather colour, paper colour, age and burnt edges, stitching, spine bands, page shape, emblem (medallion or pressed into the leather) and cover title. Make copies to create new books.
- The book can start closed: the cover swings open and the book slides to the centre.
- The page corner lifts first, then the page turns.
- Save and open projects (.hmproj).
- Windows installer with automatic update checks.
