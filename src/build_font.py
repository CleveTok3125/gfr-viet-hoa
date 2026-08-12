"""Build a single-channel SDF bitmap font (.msg + .wtb) from a TTF/OTF.

The game pipelines fonts as a .msg (msgpack: info / character / kerning) plus
one or more .wtb textures. Each .wtb is a "WTB\\0" container holding a DDS
DX10 BC4_UNORM atlas (a single-channel signed distance field, boundary 128).

This module regenerates such a font from an OFL source (Barlow Medium) using
Unicode code points directly (ASCII + Latin-ext + Vietnamese
U+1EA0..U+1EFF), so the game looks glyphs up without slot remapping.

Layout follows the game's own font conventions (reverse-engineered from the
archived yoongothic and the patched fttk_yoongothic750 font):
  * ink box (xMin..xMax, yMin..yMax) comes from the rasterized mask (TTF
    y-up, baseline at 0) rounded to the final-pixel grid;
  * quad = ink box +/- padding, packed into 2048x2048 pages;
  * offsetX = floor(glyph_bx) - padding        (glyph_bx = xMin * scale)
  * offsetY = base - floor(glyph_by) - padding (glyph_by = yMax * scale)
  * advance = round(glyph_advance)             (glyph_advance = aw * scale)
Each page is written as <out>/<base>_<n>.wtb (n = page index + 1) and the msg
pages entries point at <base><n> to match the data/fonts.zip install layout.

Usage:
    python3 -m src.build_font --font data/fonts_src/Barlow-Medium.ttf \
        --out build/font --name fttk_yoongothic750 --size 38 --padding 6

References: Nenkai/GBFRDataTools TextureBinHeader/TextureBin (WTB container),
PatchAddresses (msg format).
"""
import argparse
import math
import os
import struct

import msgpack
import numpy as np
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

MAGIC = 0x425457  # "WTB\0"
PAGE = 2048

# SDF slope measured on the patched yoongothic font: value 128 at the
# boundary, ~ +16 per pixel of distance inside.
SDF_SLOPE = 16.0

# Supersampling factor used when rasterizing before the signed-distance
# transform (each final pixel covers SS x SS source pixels).
SS = 8


def _fnv1a(data):
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def dds_header(hgt, wdt):
    """148-byte payload: 'DDS ' + 124-byte DDS_HEADER + 20-byte DDS_HEADER_DXT10.

    Matches the vanilla fonts byte-for-byte: DXGI_FORMAT 80 (BC4_UNORM, a
    single-channel SDF), DDSD_LINEARSIZE (not PITCH), 0 mipmaps, 0 caps.
    """
    hdr = struct.pack(
        "<7I", 124, 0xA1007, hgt, wdt, (wdt * hgt) // 2, 1, 0
    ) + b"\0" * 44 + struct.pack(
        "<8I", 32, 0x04, 0x30315844, 0, 0, 0, 0, 0
    ) + struct.pack("<5I", 0, 0, 0, 0, 0)
    assert len(hdr) == 124
    dx10 = struct.pack("<5I", 80, 3, 0, 1, 0)  # BC4_UNORM, TEXTURE2D
    return b"DDS " + hdr + dx10


def _bc4_palette(r0, r1):
    """8-entry BC4 palette (r0>r1 guaranteed by the caller).

    Standard BC4 6-step palette (used by D3D hardware decode), denom 7.
    """
    p = [r0, r1]
    for i in range(2, 8):
        p.append(max(0, min(255, ((8 - i) * r0 + (i - 1) * r1) // 7)))
    return p


def bc4_encode(gray):
    """Encode a (h, w) uint8 single-channel image as BC4 (8 bytes/4x4 block)."""
    h, w = gray.shape
    assert h % 4 == 0 and w % 4 == 0
    out = bytearray((h // 4) * (w // 4) * 8)
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            blk = gray[by:by + 4, bx:bx + 4].ravel()
            r0 = int(blk.max())
            r1 = int(blk.min())
            if r0 <= r1:
                r0 = min(255, r0 + 1)
                r1 = max(0, r1 - 1)
                if r0 < r1:
                    r0, r1 = r1, r0
            pal = _bc4_palette(r0, r1)
            idx = 0
            for px in range(16):
                v = int(blk[px])
                best = min(range(8), key=lambda k: abs(pal[k] - v))
                idx |= best << (3 * px)
            o = ((by // 4) * (w // 4) + (bx // 4)) * 8
            out[o] = r0
            out[o + 1] = r1
            out[o + 2:o + 8] = idx.to_bytes(6, "little")
    return bytes(out)


def write_wtb(path, gray, pw=PAGE, ph=PAGE):
    """Write a single-texture WTB\0 container (DDS DX10/BC4 SDF payload)."""
    payload = dds_header(ph, pw) + bc4_encode(gray)

    pre = bytearray(0x1000)
    struct.pack_into("<7I", pre, 0, MAGIC, 3, 1,
                     0x20, 0x40, 0x60, 0x80)
    struct.pack_into("<I", pre, 0x20, 0x1000)      # offsets[0]
    struct.pack_into("<I", pre, 0x40, len(payload))  # sizes[0]
    struct.pack_into("<I", pre, 0x60, 0x20000020)     # flags[0]
    struct.pack_into("<I", pre, 0x80, _fnv1a(payload))  # hash[0]
    body = payload + b"\0" * ((-len(payload)) % 0x100)
    with open(path, "wb") as f:
        f.write(pre + body)


def rasterize_ink(mask, f, pad, base_row):
    """Extract a 1x SDF quad (ink +/- pad) from an SS-scaled binary mask.

    `mask` is 0/255 at SS resolution; `base_row` is the canvas row (ss) of the
    baseline. Returns (field, inkbox) where `field` is the HxW uint8 distance
    field covering exactly the quad and `inkbox` is the ink bbox
    (x0, y_top, x1, y_bot) in final pixels, TTF y-up, baseline at 0.
    """
    hgt, wdt = mask.shape
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    mx0, mx1 = xs.min(), xs.max() + 1
    my0, my1 = ys.min(), ys.max() + 1

    ix0, ix1 = round(mx0 / f), round(mx1 / f)
    it = (base_row - my0) / f   # ink top, TTF y-up
    ib = (base_row - my1) / f   # ink bottom (negative below baseline)
    it, ib = round(it), round(ib)

    # quad region in ss; x matches canvas, y is flipped (TTF y-up)
    qx0, qx1 = (ix0 - pad) * f, (ix1 + pad) * f
    qy0 = base_row - (it + pad) * f
    qy1 = base_row - (ib - pad) * f
    if qx0 < 0 or qy0 < 0 or qx1 > wdt or qy1 > hgt:
        return None
    assert (qx1 - qx0) % f == 0 and (qy1 - qy0) % f == 0

    crop = 2 * f
    cx0, cy0 = max(0, qx0 - crop), max(0, qy0 - crop)
    cx1, cy1 = min(wdt, qx1 + crop), min(hgt, qy1 + crop)
    sub = mask[cy0:cy1, cx0:cx1].astype(bool)

    d_in = ndimage.distance_transform_edt(sub) / f
    d_out = ndimage.distance_transform_edt(~sub) / f
    sdf = np.where(sub, d_in, -d_out)  # signed distance, in final px

    q = sdf[qy0 - cy0:qy1 - cy0, qx0 - cx0:qx1 - cx0]
    qh, qw = q.shape
    field = q.reshape(qh // f, f, qw // f, f).mean(axis=(1, 3))
    return field, (ix0, it, ix1, ib)


def build_codepoints():
    """Code points needed by the Vietnamese translation.

    Covers ASCII, the Latin-1/Latin-2 accented letters used by Vietnamese
    (including the precomposed I/U-with-tilde U+0129/U+0169 that fall outside
    the U+1EA0..U+1EFF block), the vanilla EN font's glyph set, and the
    symbols actually used by game text (arrows, stars, full-width brackets,
    etc.). Glyphs the primary font lacks are rasterized from --fallback fonts.
    """
    cps = set(range(32, 127))
    cps.update(range(0x1EA0, 0x1F00))
    cps.update([
        0x00B0, 0x00C0, 0x00C1, 0x00C2, 0x00C3, 0x00C9, 0x00CA, 0x00CD,
        0x00D2, 0x00D3, 0x00D4, 0x00D9, 0x00DA, 0x00DD, 0x00E0, 0x00E1,
        0x00E2, 0x00E3, 0x00E8, 0x00E9, 0x00EA, 0x00EC, 0x00ED, 0x00F2,
        0x00F3, 0x00F4, 0x00F5, 0x00F9, 0x00FA, 0x00FD,
        0x0102, 0x0103, 0x0110, 0x0111, 0x01A0, 0x01A1, 0x01AF, 0x01B0,
        0x20AC, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2013, 0x2014,
    ])
    # Precomposed Vietnamese I/U with tilde (used in "Vũ", "Chĩa", ...).
    # They are Latin Extended-A (U+0129/U+0169), not in the 1EA0 block.
    cps.update([0x0129, 0x0169])
    # Latin letters present in the vanilla EN font that may appear in
    # names/legacy text but are absent from the primary source.
    cps.update([0x00C4, 0x00C6, 0x00D6, 0x00DC, 0x00E4, 0x00E6, 0x00F6,
                0x00FC, 0x0114, 0x0115, 0x012C, 0x0132, 0x0138, 0x013F,
                0x0149, 0x014E])
    # Symbols used by game text (rendered as glyphs, not markers).
    cps.update([0x00A7, 0x00A9, 0x00AB, 0x00AE, 0x00BB, 0x00BF, 0x00D7,
                0x00F7, 0x2010, 0x2015, 0x2116, 0x2190, 0x2191, 0x2192,
                0x2193, 0x25A1, 0x2605, 0x2606, 0x30FB, 0xFF08, 0xFF09,
                0xFFFD])
    return sorted(cps)


def glyph_metrics(font, name, scale):
    """TTF ink bbox + metrics for `name`, scaled to final px. Y-up, base 0."""
    gs = font.getGlyphSet()
    bp = BoundsPen(gs)
    gs[name].draw(bp)
    (x0, y0, x1, y1) = bp.bounds or (0, 0, 0, 0)
    aw, lsb = font["hmtx"][name]
    return {
        "x0": x0 * scale, "x1": x1 * scale,
        "y1": y0 * scale, "y0": y1 * scale,  # TTF: y0 top, y1 bottom
        "adv": aw * scale, "lsb": lsb * scale,
    }


def extract_kerning(font, scale, cpset):
    """GPOS pair kerning -> [{first, second, amount}] in final px."""
    cmap = font.getBestCmap()
    name2cp = {name: cp for cp, name in cmap.items()}
    if "GPOS" not in font:
        return []
    gpos = font["GPOS"].table
    acc = {}
    for feat in gpos.FeatureList.FeatureRecord:
        if feat.FeatureTag != "kern":
            continue
        for lidx in feat.Feature.LookupListIndex:
            lookup = gpos.LookupList.Lookup[lidx]
            if lookup.LookupType != 2:
                continue
            for st in lookup.SubTable:
                if st.Format == 1:
                    for gi, pairset in enumerate(st.PairSet):
                        g1 = st.Coverage.glyphs[gi]
                        if name2cp.get(g1) not in cpset:
                            continue
                        for rec in pairset.PairValueRecord:
                            vr = rec.Value1
                            amt = vr.XAdvance if vr and vr.XAdvance else 0
                            g2 = rec.SecondGlyph
                            if name2cp.get(g2) in cpset and amt:
                                key = (name2cp[g1], name2cp[g2])
                                acc[key] = acc.get(key, 0) + amt * scale
                elif st.Format == 2:
                    c1 = st.ClassDef1.classDefs
                    c2 = st.ClassDef2.classDefs
                    g1cp = {g: name2cp.get(g) for g in c1}
                    g2cp = {g: name2cp.get(g) for g in c2}
                    for r1, cl in enumerate(st.Class1Record):
                        for r2, rec in enumerate(cl.Class2Record):
                            vr = rec.Value1
                            amt = vr.XAdvance if vr and vr.XAdvance else 0
                            if not amt:
                                continue
                            for ga, cls1 in c1.items():
                                if cls1 != r1 or g1cp[ga] not in cpset:
                                    continue
                                for gb, cls2 in c2.items():
                                    if cls2 != r2 or g2cp[gb] not in cpset:
                                        continue
                                    key = (g1cp[ga], g2cp[gb])
                                    acc[key] = acc.get(key, 0) + amt * scale
    out = []
    for (a, b), amt in acc.items():
        v = round(amt)
        # Clamp to the vanilla font's kern range: the source fonts ship
        # strong negative kern (up to ~-28px at 38px) that the game engine
        # applies verbatim, making glyphs overlap (e.g. "Tr", "Ty"). The stock
        # tt_pfdintextpro font stays within [-2, 2]; wider negative clamps
        # make medium/Bold text look too cramped.
        v = max(-2, min(2, v))
        if v:
            out.append({"first": a, "second": b, "amount": v})
    out.sort(key=lambda k: (k["first"], k["second"]))
    return out


def write_msg(path, info, chars, kerning):
    obj = {"info": info, "character": {"count": len(chars), "elements": chars},
           "kerning": {"count": len(kerning), "elements": kerning}}
    with open(path, "wb") as f:
        f.write(msgpack.packb(obj, use_bin_type=False))


def main():
    global SDF_SLOPE
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--font", required=True, help="input TTF/OTF (OFL source)")
    ap.add_argument("--fallback", action="append", default=[],
                    help="extra TTF/OTF used for glyphs the primary font lacks "
                         "(repeatable; tried in order)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--name", default="barlow_m", help="font base name")
    ap.add_argument("--size", type=int, default=38, help="glyph size in px")
    ap.add_argument("--padding", type=int, default=6)
    ap.add_argument("--slope", type=float, default=SDF_SLOPE)
    ap.add_argument("--page-w", type=int, default=PAGE, help="atlas width")
    ap.add_argument("--page-h", type=int, default=PAGE, help="atlas height")
    ap.add_argument("--base", type=int, default=41, help="baseline row")
    ap.add_argument("--line-height", type=int, default=63)
    ap.add_argument("--glyph-scale", type=float, default=1.0)
    ap.add_argument("--page-file", default=None,
                    help="override 'file' name in pages entries (default: base_name + page index)")
    ap.add_argument("--lineheight", type=float, default=None,
                    help="override glyph_lineheight (default: ascent - descent)")
    ap.add_argument("--ascent", type=float, default=None,
                    help="override glyph_ascent (default: font hhea ascent)")
    ap.add_argument("--decent", type=float, default=None,
                    help="override glyph_decent (default: font hhea descent)")
    ap.add_argument("--baseline-shift", type=int, default=0,
                    help="vertical glyph shift in px (negative moves glyphs "
                         "up; the game's offsetY grows downward)")
    ap.add_argument("--no-kerning", action="store_true")
    args = ap.parse_args()
    SDF_SLOPE = args.slope

    font = TTFont(args.font)
    upem = font["head"].unitsPerEm
    hhea = font["hhea"]
    cmap = font.getBestCmap()
    scale = args.size / upem
    ascent = args.ascent if args.ascent is not None else hhea.ascent * scale
    descent = args.decent if args.decent is not None else hhea.descent * scale
    base = args.base
    pw, ph = args.page_w, args.page_h
    os.makedirs(args.out, exist_ok=True)
    psname = args.name
    base_name = os.path.basename(psname)

    # Fallback chain: primary font first, then each --fallback in order.
    # Each source: (TTFont, cmap, scale, ImageFont, baseline_anchor_ss).
    # `anchor` is the SS-scaled FreeType ascent of the ImageFont; PIL's
    # ImageDraw.text places the baseline at `y + ascent`, so the rasterizer
    # must use the same ascent to recover the true baseline row.
    imgfont = ImageFont.truetype(args.font, args.size * SS)
    imgfont_ascent = imgfont.getmetrics()[0]
    sources = [(font, cmap, scale, imgfont, imgfont_ascent)]
    for fb in args.fallback:
        ffb = TTFont(fb, fontNumber=0) if fb.endswith(".ttc") else TTFont(fb)
        upem_fb = ffb["head"].unitsPerEm
        ifont = ImageFont.truetype(fb, args.size * SS)
        sources.append((ffb, ffb.getBestCmap(), args.size / upem_fb, ifont,
                        ifont.getmetrics()[0]))

    cps = build_codepoints()
    missing = [cp for cp in cps if all(c.get(cp) is None for _, c, *_ in sources)]
    if missing:
        print("NOTE: no source font has:",
              " ".join(f"U+{c:04X}" for c in missing))

    kerning = [] if args.no_kerning else extract_kerning(
        font, scale, set(cps))

    # SS-scaled rasterizer
    pad = args.padding

    pages = []
    page_arr = np.zeros((ph, pw), dtype=np.uint8)
    pages.append(page_arr)
    pos_x = pos_y = row_h = 0
    chars = []

    # Synthetic empty glyphs the game may look up for control characters:
    # 0x0 (missing/unknown glyph) and 0xa (newline), matching the working
    # patched font. UTF-8 ids equal the raw bytes here (single byte).
    for cid, adv in ((0x0, 29), (0xa, 12)):
        chars.append({
            "id": cid, "x": 0, "y": 0, "w": 0, "h": 0,
            "offsetX": -pad, "offsetY": 0,
            "advance": adv, "page": 0,
            "glyph_w": 0.0, "glyph_h": 0.0, "glyph_bx": 0.0,
            "glyph_by": 0.0, "glyph_advance": float(adv),
        })

    for cp in cps:
        # pick first source that has the glyph
        src = None
        for fsrc, csrc, sscale, ifont, anchor in sources:
            if csrc.get(cp) is not None:
                src = (fsrc, csrc, sscale, ifont, anchor)
                break
        if src is None:
            continue
        sfont, scmap, sscale, simgfont, s_anchor = src
        name = scmap.get(cp)
        if name is None or name not in sfont.getGlyphSet():
            continue
        gm = glyph_metrics(sfont, name, sscale)
        glyph_bx, glyph_by = gm["lsb"], gm["y0"]
        glyph_adv = gm["adv"]

        # The game addresses glyphs by the UTF-8 bytes of the code point read
        # as a big-endian integer (e.g. U+1EA0 "ạ" -> id 0xE1BAA0), NOT by the
        # raw code point. ASCII (single-byte UTF-8) is unchanged.
        gid = int.from_bytes(chr(cp).encode("utf-8"), "big")

        if cp == 32:
            chars.append({
                "id": gid, "x": 0, "y": 0, "w": 0, "h": 0,
                "offsetX": -pad, "offsetY": 0,
                "advance": round(glyph_adv), "page": 0,
                "glyph_w": 0.0, "glyph_h": 0.0, "glyph_bx": 0.0,
                "glyph_by": 0.0, "glyph_advance": glyph_adv,
            })
            continue

        # render glyph into a metric-sized canvas with (pad+4) px margins;
        # PIL anchors the ink bbox top-left at xy, so offset by a fixed M
        M = pad + 4
        Wc = math.ceil((gm["x1"] - gm["x0"] + 2 * M) * SS)
        Hc = math.ceil((gm["y0"] - gm["y1"] + 2 * M) * SS)
        xoff = M * SS - round(gm["lsb"] * SS)
        yoff = M * SS - s_anchor + round(gm["y0"] * SS)

        field = None
        inkbox = None
        for _ in range(3):
            img = Image.new("L", (Wc, Hc), 0)
            ImageDraw.Draw(img).text((xoff, yoff), chr(cp),
                                     font=simgfont, fill=255)
            mask = np.asarray(img, dtype=np.uint8)
            res = rasterize_ink(mask, SS, pad, yoff + s_anchor)
            if res is None:
                Wc += 8 * SS
                Hc += 8 * SS
                continue
            field, inkbox = res
            break
        if field is None:
            print(f"WARN: glyph U+{cp:04X} could not be rasterized, skipped")
            continue

        gw = inkbox[2] - inkbox[0]
        gh = inkbox[1] - inkbox[3]  # positive: top - bottom (TTF y-up)
        qw, qh = field.shape[1], field.shape[0]
        if qw > pw or qh > ph:
            print(f"WARN: glyph U+{cp:04X} too large ({qw}x{qh}), dropped")
            continue

        if pos_x + qw > pw:
            pos_x = 0
            pos_y += row_h + 4
            row_h = 0
        if pos_y + qh > ph:
            page_arr = np.zeros((ph, pw), dtype=np.uint8)
            pages.append(page_arr)
            pos_x = pos_y = row_h = 0
        if pos_x + qw > pw or pos_y + qh > ph:
            print(f"WARN: glyph U+{cp:04X} does not fit a page, dropped")
            continue

        page = pages[-1]
        field_i = np.clip(128 + field * SDF_SLOPE, 0, 255).astype(np.uint8)
        page[pos_y:pos_y + qh, pos_x:pos_x + qw] = field_i
        page_idx = len(pages) - 1

        chars.append({
            "id": gid, "x": pos_x, "y": pos_y, "w": qw, "h": qh,
            "offsetX": math.floor(glyph_bx) - pad,
            "offsetY": base - inkbox[1] - pad + args.baseline_shift,
            "advance": round(glyph_adv) + 2 * pad, "page": page_idx,
            "glyph_w": gw, "glyph_h": gh,
            "glyph_bx": glyph_bx, "glyph_by": glyph_by,
            "glyph_advance": glyph_adv,
        })
        pos_x += qw + 4
        row_h = max(row_h, qh)

    info = {
        "glyph_size": args.size,
        "glyph_scale": args.glyph_scale,
        "glyph_lineheight": round(args.lineheight if args.lineheight is not None
                                   else ascent - descent, 4),
        "glyph_baseline": 0,
        "glyph_ascent": round(ascent, 4),
        "glyph_decent": round(descent, 4),        "size": args.size,
        "padding": pad,
        "lineHeight": args.line_height,
        "base": base,
        "scaleW": pw,
        "scaleH": ph,
        "pageCount": len(pages),
        "pages": [{"id": i, "file": args.page_file if args.page_file else f"{base_name}{i + 1}"}
                  for i in range(len(pages))],
    }

    msg_path = os.path.join(args.out, psname + ".msg")
    write_msg(msg_path, info, chars, kerning)
    print(f"wrote {msg_path}: {len(chars)} glyphs, {len(kerning)} kern pairs, "
          f"{len(pages)} page(s)")
    for i, page in enumerate(pages):
        wtb_path = os.path.join(args.out, f"{psname}_{i + 1}.wtb")
        write_wtb(wtb_path, page, pw, ph)
        print(f"wrote {wtb_path} ({(page > 0).sum()} px ink)")


if __name__ == "__main__":
    main()