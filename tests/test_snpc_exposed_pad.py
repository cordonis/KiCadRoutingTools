#!/usr/bin/env python3
"""--same-net-pad-clearance: a paste-less exposed pad keeps its thermal vias.

The #581 keep-out covered every same-net SMD pad, the exposed pad included, so
with the flag set route_planes' #487 thermal via array found no site ("did not
fit") and nothing else in the chain places one. An exposed pad that carries
no paste of its own (the footprint's largest pad, is_thermal_pad signature at
a 0.5 mm floor) is now exempt from the PAD keep-out like a through-hole pad.
Its separate paste openings stay kept out (#962), so no via lands under
solder. A pad that carries paste stays kept out whole.

"Before" below is this tree with snpc_exposed_pad answering False (no pad is
an exempt exposed pad), so every comparison is this change and nothing else.
Test 8 does not go through that predicate: it pins what the plane step's via
map stamps for a board's same-net through-hole pads, which this change must
leave as upstream has it.

  1. no flag: route_planes output is the same before and after;
  2. flag, a board with no exposed pad: route_planes output and the GND
     keep-out cell set are the same before and after;
  3. flag, test_1290's ring board (a 2.4 mm paste-less GND exposed pad):
     0 vias in the pad before, the 4-via #487 array after;
  4. windowpanes: the paste openings are counted and stay kept out; on a
     3.6 mm pad the gaps between them are open, on a 1.7 mm pad the panes
     leave no site at all;
  5. pads that carry paste are not exempt: an exposed pad with its own paste,
     and an exposed pad split into four pasted copper pads;
  6. a bottom-side part behaves the same (B.Paste panes, B.Paste and *.Paste
     on the pad);
  7. SOIC-8-1EP: the name says exposed pad, but only the largest pad is exempt;
  8. through-hole pads: under the flag the plane step's via map stamps every
     same-net pad of esp_prog's GND, the six through-hole ones included, and a
     via 0.25 mm off a through-hole pad's copper stays blocked.

    python3 tests/test_snpc_exposed_pad.py
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY_ROUTER = os.path.join(ROOT, 'py_router')
sys.path.insert(0, PY_ROUTER)
sys.path.insert(0, HERE)

import obstacle_map  # noqa: E402
from kicad_parser import parse_kicad_pcb  # noqa: E402
from routing_config import GridCoord, GridRouteConfig  # noqa: E402

snpc_exposed_pad = getattr(obstacle_map, 'snpc_exposed_pad', None)
fails = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)
        if 'pytest' in sys.modules:       # pytest: fail the test case here
            raise AssertionError(f"{name}  {detail}")


def _old_rule(pad, pcb_data):
    return False            # before: no pad is an exempt exposed pad


class _before:
    """Run the block with the pre-change rule (drilled pads only)."""
    def __enter__(self):
        self.saved = obstacle_map.snpc_exposed_pad
        obstacle_map.snpc_exposed_pad = _old_rule

    def __exit__(self, *exc):
        obstacle_map.snpc_exposed_pad = self.saved


# ----------------------------------------------------------- board builders
def _write(lines):
    path = os.path.join(tempfile.mkdtemp(), 'b.kicad_pcb')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))
    return parse_kicad_pcb(path)


_HEAD = ['(kicad_pcb (version 20240108) (generator pcbnew)',
         '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (34 "B.Paste" user) (35 "F.Paste" user) (44 "Edge.Cuts" user))',
         '  (net 0 "") (net 1 "GND") (net 2 "SIG")',
         '  (gr_rect (start 0 0) (end 20 20) (stroke (width 0.1) (type default)) (layer "Edge.Cuts"))']


def qfn(ep=1.7, panes=None, ep_paste=False, split=False, side='F'):
    """QFN-16-1EP with a GND exposed pad of `ep` mm. panes=(size, offset):
    a 2x2 paste-only windowpane; ep_paste: paste on the pad itself ('*' for
    the *.Paste spelling); split: the exposed pad as four pasted copper pads;
    side='B': the part on the bottom (B.Cu / B.Paste / B.Mask)."""
    lines = _HEAD + [f'  (footprint "t:QFN-16-1EP_3x3mm" (layer "{side}.Cu") (at 10 10)',
                     f'    (property "Reference" "U1" (at 0 -3) (layer "{side}.SilkS"))']
    lead = ep / 2 + 0.6
    for i in range(16):
        edge, k = divmod(i, 4)
        off = -0.75 + 0.5 * k
        x, y = [(-lead, off), (off, lead), (lead, -off), (-off, -lead)][edge]
        net = '(net 1 "GND")' if i == 0 else '(net 2 "SIG")'
        lines.append(f'    (pad "{i + 1}" smd rect (at {x} {y}) (size 0.3 0.3) '
                     f'(layers "{side}.Cu" "{side}.Paste" "{side}.Mask") {net})')
    if split:
        q = ep / 4
        for x in (-q, q):
            for y in (-q, q):
                lines.append(f'    (pad "17" smd rect (at {x} {y}) (size {ep / 2 - 0.05} {ep / 2 - 0.05}) '
                             f'(layers "{side}.Cu" "{side}.Paste" "{side}.Mask") (net 1 "GND"))')
    else:
        paste = {True: f' "{side}.Paste"', '*': ' "*.Paste"'}.get(ep_paste, '')
        layers = f'"{side}.Cu"{paste} "{side}.Mask"'
        lines.append(f'    (pad "17" smd rect (at 0 0) (size {ep} {ep}) (layers {layers}) (net 1 "GND"))')
    if panes:
        size, off = panes
        for x in (-off, off):
            for y in (-off, off):
                lines.append(f'    (pad "" smd rect (at {x} {y}) (size {size} {size}) (layers "{side}.Paste"))')
    lines[-1] += ')'
    lines.append(')')
    return _write(lines)


def keepout(pcb, net_id=1):
    cfg = GridRouteConfig(track_width=0.15, clearance=0.15, via_size=0.4, via_drill=0.2,
                          grid_step=0.05, layers=['F.Cu', 'B.Cu'])
    cfg.same_net_pad_clearance = 0.1
    return {tuple(c) for c in obstacle_map.same_net_pad_via_keepout_cells(pcb, net_id, cfg)}, \
        GridCoord(cfg.grid_step)


def ep_cells(pcb, coord, ref='U1'):
    ep = max(pcb.footprints[ref].pads, key=lambda p: p.size_x * p.size_y)
    n = int(round(ep.size_x / 2 / 0.05))
    return {coord.to_grid(ep.global_x + dx * 0.05, ep.global_y + dy * 0.05)
            for dx in range(-n + 1, n) for dy in range(-n + 1, n)}


# ------------------------------------------------- route_planes, end to end
def _route_planes(board, extra, old_rule):
    """route_planes on `board`, in a child process; with old_rule the child
    runs snpc_exposed_pad's pre-change rule. Returns (stdout, output text)."""
    out = os.path.join(os.path.dirname(board), 'out_%d.kicad_pcb' % old_rule)
    args = [board, out, '--nets', 'GND', '--plane-layers', 'B.Cu', '--escalation', 'off',
            '--no-fix-drc-settings', '--board-edge-clearance', '0.7',
            '--hole-to-hole-clearance', '0.25', '--via-size', '0.6', '--via-drill', '0.3',
            '--clearance', '0.15', *extra]
    boot = ('import runpy, sys; sys.path.insert(0, sys.argv[1]); import obstacle_map\n'
            'if sys.argv[2] == "1":\n'
            '    obstacle_map.snpc_exposed_pad = lambda p, d: False\n'
            'sys.argv = [sys.argv[3]] + sys.argv[4:]\n'
            'runpy.run_path(sys.argv[0], run_name="__main__")\n')
    r = subprocess.run([sys.executable, '-X', 'utf8', '-c', boot, PY_ROUTER, str(int(old_rule)),
                        os.path.join(PY_ROUTER, 'route_planes.py'), *args],
                       capture_output=True, text=True, timeout=900)
    with open(out, encoding='utf-8') as fh:
        return r.stdout, fh.read()


def _norm(text):
    """Board text without the per-run uuids and timestamps."""
    text = re.sub(r'\(uuid "?[0-9a-fA-F-]+"?\)', '(uuid)', text)
    return re.sub(r'\(tstamp "?[0-9a-fA-F-]+"?\)', '(tstamp)', text)


def _stage(text):
    import test_1290_pass_rules as T
    td = tempfile.mkdtemp()
    T.stage(td, 'b', text)
    return os.path.join(td, 'b.kicad_pcb')


def _ring():
    import test_1290_pass_rules as T
    return T.ring_board()


def _no_ep():
    """The ring board with U1 a plain two-pin part: no pad is an exposed pad."""
    import test_1290_pass_rules as T
    text = T.ring_board().replace('"Package_DFN_QFN:QFN-16-1EP_3x3mm"', '"TestPoint:TP"')
    return text.replace('(size 2.4 2.4)', '(size 0.5 0.5)')


def _vias_in_ep(text, board_dir):
    path = os.path.join(board_dir, 'probe.kicad_pcb')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    pcb = parse_kicad_pcb(path)
    ep = max(pcb.footprints['U1'].pads, key=lambda p: p.size_x * p.size_y)
    return [v for v in pcb.vias if abs(v.x - ep.global_x) <= ep.size_x / 2
            and abs(v.y - ep.global_y) <= ep.size_y / 2]


# ------------------------------------------------------------------- tests
def test_no_flag_output_unchanged():
    board = _stage(_ring())
    _, before = _route_planes(board, [], old_rule=True)
    _, after = _route_planes(board, [], old_rule=False)
    check("no flag: route_planes output is the same before and after", _norm(before) == _norm(after))


def test_flag_no_ep_board_unchanged():
    board = _stage(_no_ep())
    pcb = parse_kicad_pcb(board)
    check("the board has no exempt pad",
          not any(snpc_exposed_pad and snpc_exposed_pad(p, pcb) for p in pcb.pads_by_net.get(
              next(n for n, net in pcb.nets.items() if net.name == 'GND'), [])))
    gnd = next(n for n, net in pcb.nets.items() if net.name == 'GND')
    after_cells, _ = keepout(pcb, gnd)
    with _before():
        before_cells, _ = keepout(pcb, gnd)
    check("flag: GND keep-out cells are the same before and after",
          before_cells == after_cells, f"{len(before_cells)} vs {len(after_cells)}")
    _, before = _route_planes(board, ['--same-net-pad-clearance', '0.1'], old_rule=True)
    _, after = _route_planes(board, ['--same-net-pad-clearance', '0.1'], old_rule=False)
    check("flag: route_planes output is the same before and after", _norm(before) == _norm(after))


def test_ring_board_thermal_array():
    board = _stage(_ring())
    d = os.path.dirname(board)
    _, before = _route_planes(board, ['--same-net-pad-clearance', '0.1'], old_rule=True)
    log_after, after = _route_planes(board, ['--same-net-pad-clearance', '0.1'], old_rule=False)
    v0, v1 = _vias_in_ep(before, d), _vias_in_ep(after, d)
    check("flag, before: no via in the exposed pad", len(v0) == 0, f"{len(v0)} via(s)")
    check("flag, after: the #487 array is laid (4 vias)",
          len(v1) == 4 and 'did not fit' not in log_after, f"{len(v1)} via(s)")


def test_windowpanes():
    # 3.6 mm pad, 2x2 panes of 1.2 mm at +-0.9: a 0.6 mm gap between them
    pcb = qfn(ep=3.6, panes=(1.2, 0.9))
    aps = obstacle_map.paste_keepout_apertures(pcb, 1)
    check("3.6 mm pad: its four paste openings are kept out", len(aps) == 4, f"{len(aps)} opening(s)")
    cells, coord = keepout(pcb)
    panes = [coord.to_grid(10 + x, 10 + y) for x in (-0.9, 0.9) for y in (-0.9, 0.9)]
    check("3.6 mm pad: every pane centre is kept out", all(c in cells for c in panes))
    check("3.6 mm pad: the centre gap between the panes is open", coord.to_grid(10, 10) not in cells)
    open_big = len(ep_cells(pcb, coord) - cells)
    check("3.6 mm pad: open via sites in the pad", open_big > 0, f"{open_big}")
    # 1.7 mm pad, panes of 0.6 mm at +-0.425: 0.25 mm gaps, no via fits
    pcb = qfn(ep=1.7, panes=(0.6, 0.425))
    aps = obstacle_map.paste_keepout_apertures(pcb, 1)
    check("1.7 mm pad: its four paste openings are kept out", len(aps) == 4, f"{len(aps)} opening(s)")
    cells, coord = keepout(pcb)
    open_small = len(ep_cells(pcb, coord) - cells)
    check("1.7 mm pad: the panes leave no via site", open_small == 0, f"{open_small}")


def test_pasted_pads_not_exempt():
    pcb = qfn(ep=3.6, ep_paste=True)
    ep = [p for p in pcb.footprints['U1'].pads if p.pad_number == '17']
    ok = snpc_exposed_pad is not None
    check("an exposed pad with its own paste is not exempt", ok and not snpc_exposed_pad(ep[0], pcb))
    cells, coord = keepout(pcb)
    check("... and it is kept out whole", ep_cells(pcb, coord) <= cells)
    pcb = qfn(ep=3.6, split=True)
    eps = [p for p in pcb.footprints['U1'].pads if p.pad_number == '17']
    check("split exposed pad: four pasted copper pads", len(eps) == 4)
    check("split exposed pad: none is exempt", ok and not any(snpc_exposed_pad(p, pcb) for p in eps))
    cells, coord = keepout(pcb)
    centres = [coord.to_grid(p.global_x, p.global_y) for p in eps]
    check("split exposed pad: every part is kept out", all(c in cells for c in centres))


def test_bottom_side_and_wildcard_paste():
    # a flipped part behaves as on top: its paste-less exposed pad is exempt,
    # its B.Paste windowpanes stay kept out, and B.Paste or *.Paste on the pad
    # itself makes it not exempt
    ok = snpc_exposed_pad is not None
    pcb = qfn(ep=3.6, side='B')
    ep = max(pcb.footprints['U1'].pads, key=lambda p: p.size_x * p.size_y)
    check("bottom side: the parsed exposed pad has no paste layer",
          not any(str(ln).endswith('.Paste') for ln in ep.layers), f"{ep.layers}")
    check("bottom side: a paste-less exposed pad is exempt", ok and snpc_exposed_pad(ep, pcb))
    cells, coord = keepout(pcb)
    check("bottom side: no site on the exposed pad is kept out", not (ep_cells(pcb, coord) & cells))
    pcb = qfn(ep=3.6, panes=(1.2, 0.9), side='B')
    aps = obstacle_map.paste_keepout_apertures(pcb, 1)
    check("bottom side: its four B.Paste openings are kept out", len(aps) == 4, f"{len(aps)} opening(s)")
    cells, coord = keepout(pcb)
    check("bottom side: every pane centre is kept out",
          all(coord.to_grid(10 + x, 10 + y) in cells for x in (-0.9, 0.9) for y in (-0.9, 0.9)))
    check("bottom side: the centre gap is open", coord.to_grid(10, 10) not in cells)
    for spelling, side in ((True, 'B'), ('*', 'F'), ('*', 'B')):
        pcb = qfn(ep=3.6, ep_paste=spelling, side=side)
        ep = max(pcb.footprints['U1'].pads, key=lambda p: p.size_x * p.size_y)
        name = '*.Paste' if spelling == '*' else f'{side}.Paste'
        check(f"{side} side, {name} on the pad (parsed {ep.layers}): not exempt",
              ok and not snpc_exposed_pad(ep, pcb))
        cells, coord = keepout(pcb)
        check(f"{side} side, {name} on the pad: kept out whole", ep_cells(pcb, coord) <= cells)


def test_ep_named_footprint_leads_not_exempt():
    # SOIC-8-1EP: the name says exposed pad and the 1.5 x 0.6 mm leads pass the
    # 0.5 mm floor, but only the largest pad is exempt
    lines = _HEAD + ['  (footprint "t:SOIC-8-1EP_3.9x4.9mm" (layer "F.Cu") (at 10 10)',
                     '    (property "Reference" "U2" (at 0 -4) (layer "F.SilkS"))']
    for i in range(8):
        x, y = (-2.7, -1.905 + 1.27 * i) if i < 4 else (2.7, 1.905 - 1.27 * (i - 4))
        lines.append(f'    (pad "{i + 1}" smd rect (at {x} {y}) (size 1.5 0.6) (layers "F.Cu") (net 1 "GND"))')
    lines += ['    (pad "9" smd rect (at 0 0) (size 2.4 3.1) (layers "F.Cu") (net 1 "GND")))', ')']
    pcb = _write(lines)
    pads = {p.pad_number: p for p in pcb.footprints['U2'].pads}
    ok = snpc_exposed_pad is not None
    check("the exposed pad is exempt", ok and snpc_exposed_pad(pads['9'], pcb))
    check("no lead is exempt", ok and not any(snpc_exposed_pad(pads[str(n)], pcb) for n in range(1, 9)))


def test_through_hole_pads_stamped_as_upstream():
    # Upstream's build_via_obstacle_map stamps EVERY target-net pad under the
    # flag, a through-hole pad included (the routing keep-out skips drilled
    # pads; the plane via map does not). Counted at _add_pad_via_obstacle,
    # not through snpc_exposed_pad: esp_prog's GND has no exposed pad, so the
    # stamped set must be all 17 GND pads, 6 of them through-hole, as on
    # upstream 61565f3 (measured there).
    import contextlib
    import io
    import plane_obstacle_builder as pob
    pcb = parse_kicad_pcb(os.path.join(ROOT, 'kicad_files', 'esp_prog.kicad_pcb'))
    gnd = next(n for n, net in pcb.nets.items() if net.name == 'GND')
    cfg = GridRouteConfig(track_width=0.2, clearance=0.1, via_size=0.4, via_drill=0.2,
                          grid_step=0.05, layers=['F.Cu', 'B.Cu'])
    stamped = []
    real = pob._add_pad_via_obstacle

    def spy(obstacles, pad, *a, **kw):
        if pad.net_id == gnd:
            stamped.append(pad)
        return real(obstacles, pad, *a, **kw)
    pob._add_pad_via_obstacle = spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            vm = pob.build_via_obstacle_map(pcb, cfg, gnd, verbose=False, same_net_pad_clearance=0.1)
    finally:
        pob._add_pad_via_obstacle = real
    pads = pcb.pads_by_net[gnd]
    th = [p for p in pads if getattr(p, 'drill', 0)]
    th_stamped = [p for p in stamped if getattr(p, 'drill', 0)]
    check("esp_prog GND: every pad is stamped (17)", len(stamped) == len(pads) == 17,
          f"{len(stamped)} of {len(pads)}")
    check("esp_prog GND: the through-hole pads are stamped (6)", len(th_stamped) == len(th) == 6,
          f"{len(th_stamped)} of {len(th)}")
    coord = GridCoord(cfg.grid_step)
    p = next(q for q in pcb.footprints['CON1'].pads if q.pad_number == '4')
    site = coord.to_grid(p.global_x + p.size_x / 2 + 0.25, p.global_y)
    check("a GND via 0.25 mm off CON1.4's copper is blocked", vm.is_via_blocked(*site))


TESTS = [test_no_flag_output_unchanged, test_flag_no_ep_board_unchanged, test_ring_board_thermal_array,
         test_windowpanes, test_pasted_pads_not_exempt, test_bottom_side_and_wildcard_paste,
         test_ep_named_footprint_leads_not_exempt, test_through_hole_pads_stamped_as_upstream]

if __name__ == '__main__':
    for t in TESTS:
        print(t.__name__)
        t()
    print("OK" if not fails else f"FAILED: {len(fails)} check(s): {fails}")
    sys.exit(1 if fails else 0)
