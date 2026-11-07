# Changes

## 0.10.2
- **The last page goes flat as it lands**, the same rule as the first page: once the last page is turned there is nothing left on the right to make a spread with, so it lies flat on the stack.
- **Zoom works like a real camera lens**: the camera stays where it is and the lens gets longer. Before, zooming moved the camera closer, and with a strong perspective a small book looked huge and bent, with the cover cut off. Zoom now only makes the book bigger, never distorted.

## 0.10.1
- **The book's size now shows in the video**: a smaller book looks smaller in the picture, compared with the Leather Journal (15 x 21.5 cm), in the live view and the render. Before, the camera always zoomed to fill the picture, so only the shape changed. A book bigger than the Leather Journal is still kept whole in the picture. Use the camera zoom to bring a small book closer.
- **Compare in the video view...** (in Change book design, Size and shape): the book as it is now and the new size side by side, animated, with your camera and pages, exactly as the video shows them. Play / pause and a scrub bar move both together.
- Changing the width or height no longer makes the window lag: the small preview now works from small copies of the images.

## 0.10.0
- **Pictures on a page, like layers in After Effects**: select a page and press "Pictures on this page..." (or double-click the page). Add as many pictures as you like, drag each one to move it, mouse wheel to make it bigger or smaller, Shift + wheel to turn it. Each picture also has size, turn, opacity and mirror settings, plus Centre / Fit page width / Straight buttons. Pictures can sit on blank, image or text pages.
- **Ink on the page** (the same as in StrokeScribe): the picture's own paper disappears and its lines become ink, so it looks printed on the page with the paper's grain showing through and no square around it. Ink colour (dark grey, black, sepia, brown, or the picture's own colours), paper removal and ink strength. Edges: soft edges, oval fade or no fading, with an edge size (also works with ink off).
- **Change the book's size and shape**: in "Change book design..." pick a shape (A5, pocket, tall, square, wide/landscape) or type the page width and height. A preview shows the closed and open book in the new shape, with the current shape as a dashed gold line, before anything is saved. Your cover, spine and paper images can be stretched, cropped to fill, or adjusted one by one; the required image sizes follow the new shape.
- After a shape change, page images that no longer fit the page can be adjusted for you (crop all, or one by one) or kept stretched.
- Checked: every page shape, turn style and 10 / 25 / 50 sheets with wide, square and tall books (no page touches another), in the live view and the render.

## 0.9.4
- **The curve travels with the visible pages** (Curved / Very curved): only the two pages you can see are curved; every page under them is flat. The first spread, just opened, is flat. As a page turns, it and the page it reveals on the right curve up together; the page it lands on goes flat again. Checked through every turn (and fast flips) for every turn style - no page touches another - in the live view and the render.

## 0.9.3
- **Pages are sewn to the spine, like a real book**: every sheet is sewn at its own fixed spot along the spine and turns about it. When the book opens, the spine rolls into a hump between the two covers (the bent hinge) with the pages sewn along it, so each side lies out flat and the top pages dip into the gutter. Before, pages were tied to the top of the stack, so with many pages on one side they curled up at the middle and the spine disappeared.
- The open spine is now as wide as the book is thick, so thicker books open realistically too.
- Checked: every neighbouring pair of sheets on both sides with 0, half and all pages turned; a page mid-turn against the pages sewn beside it; the moving cover; for every page shape, turn style and 10 / 25 / 50 sheets - in the live view and the render.

## 0.9.2
- **The open book is level left and right**: the open cover now lies flat at the same height as the back cover, like a real book whose hinge flexes, instead of tilting down from the top of the pages. Turned pages drape from the spine onto it, so both halves mirror each other. The cover still sits on top of the pages when closed; its hinge drops to table level as it goes over. Checked through the whole animation (opening, landing, turning) for every page shape, turn style and 10 / 25 / 50 sheets, in the live view and the render.
- The timeline bar under the live view has its own full-width row again, so you can always drag back and forth through the animation; the options (speed, repeat, turn by hand, record) are on the row below.

## 0.9.1
- Fixed: with Curved or Very curved pages, the arch pushed up through the closed front cover. Pages are now pressed flat while the book is closed and relax into their curve as the cover lifts off them (fully curved once the cover is 45% open). Checked at every cover angle for 10, 25 and 50 sheets, in the live view and the render.

## 0.9.0 - page styles and faster renders
- **Page shape** (Book section): Flat, Curved or Very curved. Curved pages rise out of the spine in a soft arch, like a real open book. Every page stays on top of the one below it.
- **Page turn style** (Animation tab): Natural (the smooth arc you had), Corner peel (like a hand-made After Effects turn: the bottom corner curls up slowly, the page whips over, then lands with its corner still curled) and Quick and light.
- **Add a fast flip...** (Animation tab): flip through many pages in a second or two, like riffling them with your thumb. Pages fan over without passing through each other; blank pages are added if the book needs more.
- **Faster renders**: frames where nothing moves are copied instead of rendered again. Photoreal keeps the scene loaded between frames, cleans up noise on the graphics card and stops sampling pixels that are already clean (about 30% faster even without a graphics card).
- **Render with 2 Blenders at once** (Settings, on by default): each renders half of the video at the same time, so your graphics card is kept busy instead of waiting.
- Thin books: the bound edges of the pages are now always at least a sheet apart at the spine.

## 0.8.3
- **Much smaller MOV files**: new "MOV file size" choice in the Export tab. "Smaller file - looks the same" (the new default) is about a quarter of the size: measured 47.6 dB against the original frames, above the ~45 dB where differences stop being visible. A 3.6 GB video becomes roughly 0.9 GB. "Maximum quality" keeps the old, very large files.
- Tip in the Export tab: 30 frames per second is plenty for page turns and halves the size again compared with 60.

## 0.8.2
- Fixed: the turning page went out of the top of the picture while it stood up mid-turn. The camera now frames the open book and the standing page together, centred, with a margin all round - on every camera preset, in the live view and the video alike. Zoom still works as before if you want it closer.

## 0.8.1
- **Adjust images for you**: if an image is not the size a cover, spine, paper or page needs, Handyman offers to adjust it - crop to fill (drag to choose what shows, wheel to zoom), fit inside (edges filled with the image's own colour) or stretch. It saves an adjusted copy; your original file is never changed. When adding several page images, "Adjust all" crops them all at once.
- The button is now called **Change book design...**
- Fixed: after saving a new design, the live view only updated later (when something else changed). It now updates right away - and also when you replace an image with a file of the same name.
- Live view lighting is neutral now: white paper stays white instead of turning yellow-green-orange on curved pages.

## 0.8.0 - easier to use
- New, simpler window laid out in the order you work: **1 Your book** and **2 Pages** on the left, the preview in the middle, and tabs for **Camera**, **Animation**, **Export** and **Settings** on the right. **Render video** is the big amber button at the top.
- **Change covers & paper...** is now a big button right under the book choice.
- **Straighten the book** (Camera tab): one click levels the picture - no sideways lean, book facing you squarely, no rotation. The default camera no longer leans.
- **Fill with blank**: one click adds blank pages until every page of the book turns. **Clear all** empties the list.
- Plain names: Render a still, Quick test video, Repeat, Turn pages by hand, Look from above, Walk around, Lean sideways, Zoom...
- Controls the Leather Journal does not use (page curl, image fit, page-image mode) are hidden for it.
- "Book position" (move / rotate / scale) is folded away under Advanced in the Camera tab.
- A fixed dark theme, so the app looks the same whatever Windows is set to.
- Live view: the back of a turning page is lit like the front, as in the render.

## 0.7.3
- **Swap any image of the Leather Journal**: Book > Edit… opens "Journal design" - front and back covers (outside and inside), spine, leather, hinge strip, and the paper for right- and left-hand pages. Each image must be exactly the size shown; a wrong size is refused with the size needed. "Original" puts back the shipped image, and "Save size guides…" saves the current images, named with their sizes, to paint over.
- Page images you add must be 982 × 1406 px for the journal (shown under the page list); wrong sizes are refused.
- Fixed: with the book rotated (3D transform), half of it disappeared in "Preview still" and renders, cut off by the table under it; in Draft/Final quality that table also rendered as a white floor. The fast modes now have no table (like the old engine) and in Photoreal the shadow surface moves with the book.
- The live view no longer gives up and switches to the flat beige fallback after a single bad frame; the error is written to Handyman\logs\live_view.log.
- Cover images are now exactly the cover's shape (1080 × 1602 px), so nothing is stretched.

## 0.7.2
- Fixed: adding pages did not add page turns to the timeline, so the video stayed at one turn (3.7 s) even with 20 pages. The timeline now follows the page list - one turn per two pages. If you edited the timeline by hand, your clips are kept and turns are only added or removed at the end.
- Fixed: "Hold at end" was ignored once the timeline had clips, so the video stopped the instant the last page landed.
- The video length shown under the preview is now the length that actually plays and renders.
- Page list labels: page 1 is on the right (the inside cover is on the left), as in the book.

## 0.7.1
- One book: **Leather Journal** (the real-pages journal). The old "Leather Book - Development Preview" and "Legacy Journal" are removed from the list; on update they are moved to the `_retired` folder inside your books folder, so nothing you changed in them is lost.
- "New Leather Book" now starts from the Leather Journal.

## 0.7.0
- New book engine for the **Journal (real pages)** template. Every sheet is a real solid sheet cut to the page's outline (rounded fore-edge corners, square at the spine), paper never stretches, the page under a turning page is always the real next page, and landed pages are kept above the open cover along their whole width, so the cover never shows through the gutter.
- The template decides the engine (`"engine": "journal"` in book.json); every other book still uses the original engine.
- Swap the covers by replacing the images in the template folder; the dimensions stay the same.
- The live preview draws journal books with the same shapes as the final render (no more old book in the preview).
- Your camera settings (preset, zoom, shift, slow move) now frame the journal book, in the preview and the render alike.
- Packaging: the Blender-side `clips.py` now ships next to `scene.py`, which imports it.

## 0.6.17
- Fixed the page shape: `page_aspect` is page height divided by width, and 0.6.15 set it to 0.702, which made the page landscape. Portrait page art (2264x3225) needs 1.424, so the journal is portrait again.

## 0.6.16
- Fixed a page turn landing on the wrong page. The first left page and the last right page (the ones a turn uncovers) were stacked *above* the turning sheets instead of below them, so a finished turn showed the wrong image — most visibly on the first turn.

## 0.6.14
- Fixed the cover fighting your artwork: the procedural tooled border, stitching and lettering are now only added to bare leather, never painted on top of a cover image you supplied. Your cover now renders exactly as designed.

## 0.6.13
- Better lighting in the render: a warm key, a soft cool fill and a warm rim, so the leather keeps its detail instead of going flat and the book lifts off the background.
- The default journal now has gold-tooled "JOURNAL" lettering (change it under Edit…), tuned so it reads as gold foil rather than grey metal.

## 0.6.12
- Fixed the update prompt offering a version you already have: a cached release is now only offered when it is newer than the running app.

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
