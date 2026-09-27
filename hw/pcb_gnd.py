"""GND connectivity helpers for the routed TouchSynth board (used by gen_pcb.py after routing).

gnd_components(): connected clusters of the GND net (fills of both layers, pads, tracks, vias).
bridge_islands(): joins every GND island to the main cluster with one straight track (optionally ending in a
                  new via onto the other layer), refills and repeats.
"""
import math
import pcbnew

MM = pcbnew.FromMM
V = pcbnew.VECTOR2I_MM
W = H = 100.0


def gnd_components(board):
    return net_components(board, "GND")


def net_components(board, netname):
    """copper clusters of one net, largest first; each = {"polys": [(layer, SHAPE_POLY_SET)], "items": [...]}"""
    gnd = board.FindNet(netname).GetNetCode()
    polys = []
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetCode() != gnd:
            continue
        L = z.GetLayer()
        f = z.GetFilledPolysList(L)
        for i in range(f.OutlineCount()):
            u = f.UnitSet(i)
            b = u.BBox()
            polys.append((L, u, (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())))
    items = [it for it in list(board.GetPads()) + list(board.GetTracks()) if it.GetNetCode() == gnd]
    ib = []
    for it in items:
        b = it.GetBoundingBox()
        ib.append((b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()))
    n0 = len(polys)
    par = list(range(n0 + len(items)))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    def ov(a, c):
        return a[0] <= c[2] and c[0] <= a[2] and a[1] <= c[3] and c[1] <= a[3]

    for j, it in enumerate(items):
        for k, (L, u, bb) in enumerate(polys):
            if it.IsOnLayer(L) and ov(ib[j], bb) and it.GetEffectiveShape(L).Collide(u, 0):
                par[find(n0 + j)] = find(k)
        for k in range(j + 1, len(items)):
            if ov(ib[j], ib[k]):
                o = items[k]
                for L in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
                    if it.IsOnLayer(L) and o.IsOnLayer(L) and \
                            it.GetEffectiveShape(L).Collide(o.GetEffectiveShape(L), 0):
                        par[find(n0 + j)] = find(n0 + k)
                        break
    comps = {}
    for n in range(len(par)):
        c = comps.setdefault(find(n), {"polys": [], "items": []})
        if n < n0:
            c["polys"].append(polys[n][:2])
        else:
            c["items"].append(items[n - n0])
    return sorted(comps.values(), key=lambda c: -(len(c["items"]) + len(c["polys"])))


def refill(board):
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()


def bridge_islands(board, clr=0.22, tw=0.3, via_d=0.6, drill=0.3, rounds=3):
    gnd = board.FindNet("GND")
    SC, SS = pcbnew.SHAPE_CIRCLE, pcbnew.SHAPE_SEGMENT
    left = 0
    for rnd in range(rounds):
        comps = gnd_components(board)
        left = len(comps) - 1
        print(f"bridge round {rnd}: {left} GND islands")
        if left == 0:
            return 0
        mainpolys = {L: [u for l, u in comps[0]["polys"] if l == L] for L in (pcbnew.F_Cu, pcbnew.B_Cu)}
        other = [it for it in list(board.GetPads()) + list(board.GetTracks())
                 if it.GetNetCode() != gnd.GetNetCode()]
        obox = []
        for it in other:
            b = it.GetBoundingBox()
            obox.append((pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()),
                         pcbnew.ToMM(b.GetBottom())))
        track_ban = {L: [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowTracks()
                         and z.IsOnLayer(L)] for L in (pcbnew.F_Cu, pcbnew.B_Cu)}
        via_ban = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]

        def clear(shape, layers, box):
            for (x0, y0, x1, y1), it in zip(obox, other):
                if x1 < box[0] or x0 > box[2] or y1 < box[1] or y0 > box[3]:
                    continue
                for L in layers:
                    if it.IsOnLayer(L) and it.GetEffectiveShape(L).Collide(shape, MM(clr)):
                        return False
            return True

        def in_main(L, x, y, r):
            pts = [(x, y)] + [(x + r * math.cos(k * math.pi / 4), y + r * math.sin(k * math.pi / 4))
                              for k in range(8)]
            return any(all(u.Contains(V(px, py)) for px, py in pts) for u in mainpolys[L])

        for comp in comps[1:]:
            starts = []
            for it in comp["items"]:
                if it.GetClass() in ("PCB_VIA", "PAD"):
                    p = it.GetPosition()
                    starts.append((pcbnew.ToMM(p.x), pcbnew.ToMM(p.y),
                                   [L for L in (pcbnew.F_Cu, pcbnew.B_Cu) if it.IsOnLayer(L)]))
            best = None
            for sx, sy, layers in starts:
                for L in layers:
                    Lo = pcbnew.B_Cu if L == pcbnew.F_Cu else pcbnew.F_Cu
                    for k in range(24):
                        a = 2 * math.pi * k / 24
                        for i in range(2, 41):
                            d = i * 0.25
                            if best and d >= best[0]:
                                break
                            ex, ey = sx + d * math.cos(a), sy + d * math.sin(a)
                            if not (1.5 < ex < W - 1.5 and 1.5 < ey < H - 1.5):
                                break
                            if any(z.Outline().Contains(V(ex, ey)) for z in track_ban[L]):
                                break
                            box = (min(sx, ex) - 1, min(sy, ey) - 1, max(sx, ex) + 1, max(sy, ey) + 1)
                            if not clear(SS(V(sx, sy), V(ex, ey), MM(tw)), [L], box):
                                break                       # longer ones in this direction collide as well
                            if in_main(L, ex, ey, tw / 2 + 0.05):
                                best = (d, L, sx, sy, ex, ey, False)
                                break
                            if in_main(Lo, ex, ey, via_d / 2 + 0.05) \
                                    and not any(z.Outline().Contains(V(ex, ey)) for z in via_ban) \
                                    and clear(SC(V(ex, ey), MM(via_d / 2)), [pcbnew.F_Cu, pcbnew.B_Cu], box):
                                best = (d, L, sx, sy, ex, ey, True)
                                break
            if best is None:
                p = comp["items"][0].GetPosition() if comp["items"] else None
                print("bridge: no straight bridge for the island at",
                      f"({pcbnew.ToMM(p.x):.1f}, {pcbnew.ToMM(p.y):.1f})" if p else "(fill only)")
                continue
            d, L, sx, sy, ex, ey, via = best
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(V(sx, sy)); t.SetEnd(V(ex, ey)); t.SetWidth(MM(tw)); t.SetLayer(L); t.SetNet(gnd)
            board.Add(t)
            if via:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(V(ex, ey)); v.SetDrill(MM(drill)); v.SetWidth(MM(via_d)); v.SetNet(gnd)
                board.Add(v)
        refill(board)
    left = len(gnd_components(board)) - 1
    print(f"GND islands left: {left}")
    return left


def _touch(a, b):
    for L in (pcbnew.F_Cu, pcbnew.B_Cu):
        if a.IsOnLayer(L) and b.IsOnLayer(L) and a.GetEffectiveShape(L).Collide(b.GetEffectiveShape(L), 0):
            return True
    return False


def _local_group(seed, pool):
    """items of `pool` connected to `seed` by direct copper contact (no zones)"""
    group, todo = [seed], [seed]
    rest = [it for it in pool if it is not seed]
    while todo:
        cur = todo.pop()
        hit = [it for it in rest if _touch(cur, it)]
        rest = [it for it in rest if not any(it is h for h in hit)]
        group += hit
        todo += hit
    return group


def link_islands(board, freeroute, passes=10, max_links=40):
    """let Freerouting connect every GND island to the main GND cluster: each island and the nearest pad of the
    main cluster (with the copper directly attached to it) are moved to a temporary net GNDLINK_k, routed as an
    ordinary two-pin connection, then everything is put back on GND."""
    comps = gnd_components(board)
    if len(comps) <= 1:
        return 0
    gnd = board.FindNet("GND")
    main_items = comps[0]["items"]
    main_pads = [it for it in main_items if it.GetClass() == "PAD"]
    used = set()
    links = []
    for k, comp in enumerate(comps[1:max_links + 1]):
        pads = [it for it in comp["items"] if it.GetClass() == "PAD"]
        if not pads:
            continue
        p0 = pads[0].GetPosition()
        cands = sorted(main_pads, key=lambda q: (q.GetPosition() - p0).EuclideanNorm())
        for q in cands[:12]:
            key = q.m_Uuid.AsString()
            if key in used:
                continue
            near = [it for it in main_items if (it.GetPosition() - q.GetPosition()).EuclideanNorm() < MM(6)]
            grp = _local_group(q, near)
            used.update(it.m_Uuid.AsString() for it in grp if it.GetClass() == "PAD")
            ni = pcbnew.NETINFO_ITEM(board, f"GNDLINK_{k}")
            board.Add(ni)
            for it in comp["items"] + grp:
                it.SetNet(ni)
            links.append(ni)
            break
    print(f"GND links to route: {len(links)}")
    if not links:
        return 0
    freeroute(board, passes)
    names = {ni.GetNetname() for ni in links}
    for it in list(board.GetPads()) + list(board.GetTracks()):
        if it.GetNetname() in names:
            it.SetNet(gnd)
    for ni in links:
        try:
            board.Remove(ni)
        except Exception as e:
            print("net remove:", e)
    refill(board)
    return len(links)
