#!/usr/bin/env python3
"""Remove the date from the status bar of iPad App Store screenshots.

iPadOS 26/27 draws the status bar as "<time>  <date>  <app name>" on the left. With
`simctl status_bar override --time` (the clean 12:00 every set uses) the simulator
renders that date in English whatever the system language is — "Wed 1 Nov" on a Danish
iPad whose own calendar says "søn. 1. nov." — so a localized set would ship an English
date. This drops the second text cluster (the date) and closes the gap, leaving
"<time>  <app name>"; the time keeps the locale's format (12.00 / 12:00 / 12:00 p.m.).

Clusters are runs of non-background columns in the top rows, split at gaps of 20 px or
more (words inside a cluster sit 9–14 px apart, clusters 23–24 px). Files with fewer
than three clusters on the left are left alone (en-US keeps its English date).

Usage: strip-ipad-status-date.py FILE.png...   (rewrites the files in place)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

BAND = 60          # status-bar rows (text sits on rows 20–46 at 2064 px wide)
LEFT = 0.6         # only the left part; the wifi/battery icons stay where they are
CLUSTER_GAP = 20   # px between clusters, see above


def clusters(mask):
    cols = np.where(mask.any(axis=0))[0]
    if len(cols) == 0:
        return []
    out = [[cols[0], cols[0]]]
    for c in cols[1:]:
        if c - out[-1][1] >= CLUSTER_GAP:
            out.append([c, c])
        else:
            out[-1][1] = c
    return out


def strip(path: Path) -> str:
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).copy()
    w = a.shape[1]
    band = a[:BAND, : int(w * LEFT)].astype(int)
    bg = np.median(band.reshape(-1, 3), axis=0)
    mask = np.abs(band - bg).sum(axis=2) > 60
    cl = clusters(mask)
    if len(cl) < 3:
        return f"{path}: {len(cl)} cluster(s) on the left, unchanged"
    date_start = cl[1][0]
    name_start = cl[2][0]
    shift = name_start - date_start
    end = int(w * LEFT)
    src = a[:BAND, name_start:end].copy()
    a[:BAND, date_start:end] = bg.astype(a.dtype)
    a[:BAND, date_start:date_start + src.shape[1]] = src
    Image.fromarray(a).save(path)
    return f"{path}: removed date columns {date_start}–{cl[1][1]}, app name moved left by {shift} px"


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(strip(Path(f)))
