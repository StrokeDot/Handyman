# Changes

## 0.6.11
- Turned the glTF viewport back off: showing Qt WebEngine next to the OpenGL view kept making the app close. The Live 3D view and the Blender previews are the reliable views.

## 0.6.10
- Fixed the black 3D view: Qt WebEngine is now loaded only when you open the glTF viewport, and the OpenGL context is shared up front, so it can no longer break the Live 3D view.
- Also makes switching between the 3D view and the glTF viewport safe.

## 0.6.9
- The update check no longer fails with "rate limit exceeded": a successful check is cached for six hours, manual checks still go out, the request is conditional (ETag), and a 403/429 is remembered until GitHub's reset time instead of being retried.
- The app stays usable when GitHub is unreachable, showing the last known result.
- The status message says when the next check is possible.
- Added an optional static update-metadata path that needs no GitHub API call.

## 0.6.8
- Fixed the glTF viewport showing a broken book: the app now uses your calibrated cover, pastedown and spine artwork by default, and the page block is solid.
- Fixed the app closing when switching from the glTF viewport back to Live 3D view (WebEngine uses software rendering, and the viewer pauses while hidden).

## 0.6.7
- The glTF viewport now shows the image-first book: your cover and spine artwork on simple boards with a real page stack and a deforming hinge, instead of the procedural leather.
- The cover, hinge and page animations are baked into the exported glTF (morph targets for the hinge and page).
- Repeated artwork swapping leaves the animation untouched (verified: identical silhouettes).

## 0.6.6
- Fixed the glTF viewport showing "load failed": the viewer and the book are now served from a tiny localhost server, because Chromium refuses to read the `.glb` from a `file://` URL.
- The viewport reports the real load error instead of a bare message.

## 0.6.5
- New **glTF Viewport (Beta)** toggle: an interactive Three.js viewport that plays the book exported from the Blender master template — orbit, pan, zoom and frame scrubbing. The OpenGL viewport stays the default and the fallback.
- The app can export the current book to glTF: the cover, hinge, page and spine animation are baked to morph targets so they survive the export.
- Qt WebEngine is bundled for the new viewport; if it is unavailable, the old viewport keeps working.

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
