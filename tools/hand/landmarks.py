# joints on the back-of-hand photo, in the 1000 px preview's pixels (photo = x 1.254)
FINGERS = {   # tip, DIP, PIP, MCP  with radius (px) at each
    'index':  [((172, 62), 21), ((190, 112), 24), ((218, 190), 26), ((282, 330), 30)],
    'middle': [((240, 18), 22), ((258, 72), 25), ((290, 145), 27), ((355, 305), 31)],
    'ring':   [((327, 32), 21), ((345, 88), 23), ((378, 165), 25), ((432, 305), 29)],
    'pinky':  [((442, 88), 18), ((452, 135), 20), ((470, 195), 22), ((505, 330), 25)],
    'thumb':  [((118, 330), 24), ((170, 392), 28), ((222, 462), 32), ((327, 494), 36)],
}
WRIST = [((360, 600), 0), ((470, 600), 0), ((575, 585), 0)]
PALM_EDGE = [((545, 440), 0), ((250, 500), 0)]
SLEEVE = ((490, 640), (820, 1000))     # start (cuff) and end of the forearm axis

# joints on the palm photo, in the photo's own pixels (1499 x 1390): tip, DIP, PIP, MCP
PALM_FINGERS = {
    'pinky':  [(52, 337), (82, 375), (127, 435), (262, 562)],
    'ring':   [(105, 150), (142, 210), (210, 292), (352, 450)],
    'middle': [(202, 37), (247, 112), (315, 210), (450, 390)],
    'index':  [(397, 22), (450, 105), (517, 217), (600, 360)],
    'thumb':  [(885, 127), (900, 285), (915, 450), (840, 705)],
}
PALM_WRIST = (780, 840)

# where the sleeve starts in each photo (a line; the sleeve is on the far side, larger y), photo pixels
BACK_CUFF = ((480, 795), (773, 627))
PALM_CUFF = ((683, 1233), (1025, 941))
PALM_WRIST_THUMB = (930, 800)
PALM_WRIST_PINKY = (560, 930)

# the wrist on the back photo, in photo pixels: centre, thumb side, little-finger side
BACK_WRIST3 = ((596, 666), (499, 690), (697, 619))
BACK_CUFF = ((470, 782), (765, 612))
