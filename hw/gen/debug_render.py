#!/usr/bin/env python3
"""Draw .debug/route.json: courtyards, pads, routed copper and the router's
obstacle map, so a routing failure can be looked at instead of guessed at.
Needs matplotlib (system python), not pcbnew."""
import json, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", ".debug")
d = json.load(open(os.path.join(D, "route.json")))
layer = sys.argv[1] if len(sys.argv) > 1 else "F"
own = np.load(os.path.join(D, f"route_{layer}.npy"))
zoom = [float(v) for v in sys.argv[2:6]] if len(sys.argv) >= 6 else [0, 0, d["w"], d["h"]]
fig, ax = plt.subplots(figsize=(22, 22 * (zoom[3]-zoom[1]) / (zoom[2]-zoom[0]) + 1), dpi=110)
img = np.zeros(own.shape + (3,))
img[own > 0] = (0.85, 0.9, 1.0)
img[own < 0] = (1.0, 0.8, 0.8)
img[own == 0] = (1, 1, 1)
ax.imshow(img, extent=(0, d["w"], d["h"], 0), origin="upper", interpolation="nearest")
for fp in d["fps"]:
    x0, y0, x1, y1 = fp["crt"]
    ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, fill=False, ec="#999", lw=0.6))
    ax.text((x0+x1)/2, y0-0.2, fp["ref"], fontsize=7, ha="center", color="#555", clip_on=True)
    for px0, py0, px1, py1, net, hole in fp["pads"]:
        ax.add_patch(Rectangle((px0, py0), px1-px0, py1-py0, fc="#d4a017" if not hole else "#888", ec="none", alpha=0.8))
        if net:
            ax.text((px0+px1)/2, (py0+py1)/2, net.lstrip("/")[:8], fontsize=4, ha="center", va="center", clip_on=True)
for net, back, a, c, w in d["tracks"]:
    ax.plot([a[0], c[0]], [a[1], c[1]], color="#1f5fbf" if back else "#c0392b", lw=w*6, alpha=0.8, solid_capstyle="round")
for net, x, y in d["vias"]:
    ax.plot(x, y, "o", ms=4, color="#2a7")
ax.set_xlim(zoom[0], zoom[2]); ax.set_ylim(zoom[3], zoom[1]); ax.set_aspect("equal")
ax.set_title(d["err"][:160], fontsize=10)
out = os.path.join(D, f"route_{layer}.png")
plt.savefig(out, bbox_inches="tight"); print(out)
