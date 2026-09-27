"""Small grid maze router (A*) for the connections Freerouting leaves open.

For every net that is still split into several copper clusters, the smallest cluster is routed to the rest on
F.Cu / B.Cu with vias. Obstacles are the real copper shapes of other nets (checked with KiCad's collision
functions at every grid cell, with the discretisation error added to the clearance) and the rule areas that
forbid tracks or vias. A plane of the same net (In1 / In2) counts as a target: the route may end in a via there.
"""
import heapq
import math
import pcbnew
import pcb_gnd

MM = pcbnew.FromMM
V = pcbnew.VECTOR2I_MM
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)


def _bb(it):
    b = it.GetBoundingBox()
    return (pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()), pcbnew.ToMM(b.GetBottom()))


class Grid:
    def __init__(self, board, net, win, g, tw, clr, via_d):
        self.board, self.win, self.g = board, win, g
        self.nx = int((win[2] - win[0]) / g) + 1
        self.ny = int((win[3] - win[1]) / g) + 1
        slack = g * 0.75                                   # max distance of a segment from the cell centres
        self.r_trk = tw / 2 + clr + slack
        self.r_via = via_d / 2 + clr + slack
        others = []
        for it in list(board.GetPads()) + list(board.GetTracks()):
            if it.GetNetCode() == net.GetNetCode():
                continue
            b = _bb(it)
            if b[2] < win[0] - 2 or b[0] > win[2] + 2 or b[3] < win[1] - 2 or b[1] > win[3] + 2:
                continue
            extra = 0.8 if it.GetClass() == "PAD" and it.GetParentFootprint().GetReference().startswith("KEY")                 else 0.0                                   # touch pads carry a 1 mm local clearance
            others.append((b, it, extra))
        self.buckets = {}
        for b, it, extra in others:
            for bx in range(int(b[0]) - 2, int(b[2]) + 3):
                for by in range(int(b[1]) - 2, int(b[3]) + 3):
                    self.buckets.setdefault((bx, by), []).append((it, extra))
        rules = [z for z in board.Zones() if z.GetIsRuleArea()]
        self.track_ban = {L: [z for z in rules if z.GetDoNotAllowTracks() and z.IsOnLayer(L)] for L in LAYERS}
        self.via_ban = [z for z in rules if z.GetDoNotAllowVias()]
        self.holes = [(pcbnew.ToMM(f.GetPosition().x), pcbnew.ToMM(f.GetPosition().y))
                      for f in board.GetFootprints() if f.GetReference().startswith("H")]
        self._free = {}
        self._via = {}

    def xy(self, i, j):
        return self.win[0] + i * self.g, self.win[1] + j * self.g

    def _hit(self, L, x, y, r):
        s = pcbnew.SHAPE_CIRCLE(V(x, y), MM(r))
        for it, extra in self.buckets.get((int(x), int(y)), ()):
            if it.IsOnLayer(L) and it.GetEffectiveShape(L).Collide(s, MM(extra)):
                return True
        return False

    @staticmethod
    def _in(zones, x, y, r):
        p = V(x, y)
        return any(z.Outline().Contains(p) or z.Outline().Collide(p, MM(r)) for z in zones)

    def free(self, l, i, j):
        k = (l, i, j)
        if k not in self._free:
            x, y = self.xy(i, j)
            L = LAYERS[l]
            ok = 1.2 < x < 98.8 and 1.2 < y < 98.8 and not self._hit(L, x, y, self.r_trk)
            ok = ok and not self._in(self.track_ban[L], x, y, self.r_trk - 0.2)
            self._free[k] = ok
        return self._free[k]

    def via_ok(self, i, j):
        k = (i, j)
        if k not in self._via:
            x, y = self.xy(i, j)
            ok = self.free(0, i, j) and self.free(1, i, j)
            ok = ok and not any(self._hit(L, x, y, self.r_via) for L in LAYERS)
            ok = ok and not self._in(self.via_ban, x, y, self.r_via - 0.2)
            ok = ok and all(math.hypot(x - hx, y - hy) > 3.3 for hx, hy in self.holes)
            self._via[k] = ok
        return self._via[k]


def _cells_in(grid, items, polys):
    """(layer, i, j) cells lying on the given items; plus via cells inside the given plane polygons"""
    cells, via_goal = set(), set()
    g, w = grid.g, grid.win
    for it in items:
        b = _bb(it)
        for L_i, L in enumerate(LAYERS):
            if not it.IsOnLayer(L):
                continue
            sh = it.GetEffectiveShape(L)
            for i in range(max(0, int((b[0] - w[0]) / g)), min(grid.nx, int((b[2] - w[0]) / g) + 2)):
                for j in range(max(0, int((b[1] - w[1]) / g)), min(grid.ny, int((b[3] - w[1]) / g) + 2)):
                    x, y = grid.xy(i, j)
                    if sh.Collide(pcbnew.SHAPE_CIRCLE(V(x, y), MM(0.01)), 0):
                        cells.add((L_i, i, j))
    for u in polys:
        b = u.BBox()
        x0, y0 = pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop())
        x1, y1 = pcbnew.ToMM(b.GetRight()), pcbnew.ToMM(b.GetBottom())
        for i in range(max(0, int((x0 - w[0]) / g)), min(grid.nx, int((x1 - w[0]) / g) + 2), 2):
            for j in range(max(0, int((y0 - w[1]) / g)), min(grid.ny, int((y1 - w[1]) / g) + 2), 2):
                x, y = grid.xy(i, j)
                if u.Contains(V(x, y)) and all(u.Contains(V(x + dx, y + dy)) for dx, dy in
                                               ((0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5))):
                    via_goal.add((i, j))
    return cells, via_goal


def _astar(grid, src, dst, via_goal, via_cost=6.0):
    goals = [(i, j) for _, i, j in dst] + list(via_goal)
    if not goals:
        return None
    gi = [p[0] for p in goals]
    gj = [p[1] for p in goals]
    box = (min(gi), min(gj), max(gi), max(gj))
    def h(i, j):                                           # distance to the goals' bounding box
        di = max(box[0] - i, 0, i - box[2])
        dj = max(box[1] - j, 0, j - box[3])
        return math.hypot(di, dj)
    openq, came, cost = [], {}, {}
    for s in src:
        cost[s] = 0.0
        heapq.heappush(openq, (h(s[1], s[2]), 0.0, s))
    steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    n = 0
    while openq:
        f, c, cur = heapq.heappop(openq)
        if c > cost.get(cur, 1e18):
            continue
        l, i, j = cur
        if cur in dst:
            return _unwind(came, cur), False
        if (i, j) in via_goal and grid.via_ok(i, j):
            return _unwind(came, cur), True
        n += 1
        if n > 3000000:
            return None
        for di, dj, sc in steps:
            ni, nj = i + di, j + dj
            nxt = (l, ni, nj)
            if not (0 <= ni < grid.nx and 0 <= nj < grid.ny):
                continue
            if nxt not in dst:                            # target pads may sit close to other copper
                if not grid.free(l, ni, nj):
                    continue
                if di and dj and not (grid.free(l, i + di, j) and grid.free(l, i, j + dj)):
                    continue
            nc = c + sc
            if nc < cost.get(nxt, 1e18):
                cost[nxt] = nc; came[nxt] = cur
                heapq.heappush(openq, (nc + h(ni, nj), nc, nxt))
        if grid.via_ok(i, j):
            nxt = (1 - l, i, j)
            nc = c + via_cost
            if nc < cost.get(nxt, 1e18):
                cost[nxt] = nc; came[nxt] = cur
                heapq.heappush(openq, (nc + h(i, j), nc, nxt))
    return None


def _unwind(came, cur):
    path = [cur]
    while cur in came:
        cur = came[cur]
        path.append(cur)
    return path[::-1]


def _emit(board, net, grid, path, end_via, tw, via_d, drill, lock=False):
    runs = []                                              # [(layer, [points])]
    for l, i, j in path:
        p = grid.xy(i, j)
        if runs and runs[-1][0] == l:
            runs[-1][1].append(p)
        else:
            runs.append((l, [p]))
    for k, (l, pts) in enumerate(runs):
        keep = [pts[0]]
        for a in range(1, len(pts) - 1):                   # drop points where the direction does not change
            d1 = (pts[a][0] - keep[-1][0], pts[a][1] - keep[-1][1])
            d2 = (pts[a + 1][0] - pts[a][0], pts[a + 1][1] - pts[a][1])
            if abs(d1[0] * d2[1] - d1[1] * d2[0]) > 1e-9:
                keep.append(pts[a])
        if len(pts) > 1:
            keep.append(pts[-1])
        keep = [q for i, q in enumerate(keep) if i in (0, len(keep) - 1)
                or math.dist(q, keep[i - 1]) > 0.12]          # no sliver segments (they end up dangling)
        for p, q in zip(keep, keep[1:]):
            _track(board, net, p, q, LAYERS[l], tw, lock)
        if k < len(runs) - 1:
            _via(board, net, pts[-1], via_d, drill, lock)
    if end_via:
        _via(board, net, runs[-1][1][-1], via_d, drill, lock)


def _track(board, net, a, b, L, tw, lock=False):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(*a)); t.SetEnd(V(*b)); t.SetWidth(MM(tw)); t.SetLayer(L); t.SetNet(net); t.SetLocked(lock)
    board.Add(t)


def _via(board, net, p, via_d, drill, lock=False):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(*p)); v.SetWidth(MM(via_d)); v.SetDrill(MM(drill)); v.SetNet(net); v.SetLocked(lock)
    board.Add(v)


def route_leftovers(board, g=0.15, tw=0.25, clr=0.2, via_d=0.6, drill=0.3, skip=("GND",), only=None, lock=False):
    """only: route just these nets (e.g. plane nets before Freerouting); lock: lock the new copper"""
    pcb_gnd.refill(board)
    nets = list(only) if only else sorted({it.GetNetname() for it in board.GetPads() if it.GetNetCode() > 0})
    done, failed = 0, []
    for name in nets:
        if name in skip:
            continue
        net = board.FindNet(name)
        for attempt in range(8):
            comps = pcb_gnd.net_components(board, name)
            if len(comps) <= 1:
                break
            src_c = comps[-1]
            rest_items = [it for c in comps[:-1] for it in c["items"]]
            rest_polys = [u for c in comps[:-1] for L, u in c["polys"] if L not in LAYERS]
            sp = [it.GetPosition() for it in src_c["items"]]
            if not sp:
                break
            near = min(rest_items, key=lambda it: min((it.GetPosition() - p).EuclideanNorm() for p in sp))
            routed = False
            for margin in (4.0, 10.0, 100.0):
                bbs = [_bb(it) for it in src_c["items"]] + [_bb(near)]
                win = (min(b[0] for b in bbs) - margin, min(b[1] for b in bbs) - margin,
                       max(b[2] for b in bbs) + margin, max(b[3] for b in bbs) + margin)
                win = (max(win[0], 0.5), max(win[1], 0.5), min(win[2], 99.5), min(win[3], 99.5))
                grid = Grid(board, net, win, g, tw, clr, via_d)
                src, _ = _cells_in(grid, src_c["items"], [])
                dst, vgoal = _cells_in(grid, rest_items, rest_polys)
                src = {s for s in src if grid.free(*s)} or src
                res = _astar(grid, src, dst, vgoal)
                if res:
                    path, end_via = res
                    _emit(board, net, grid, path, end_via, tw, via_d, drill, lock)
                    pcb_gnd.refill(board)
                    done += 1
                    routed = True
                    print(f"maze: routed {name} ({len(path)} cells{', via to plane' if end_via else ''})")
                    break
            if not routed:
                failed.append(name)
                print(f"maze: could not route {name}")
                break
    return done, failed
