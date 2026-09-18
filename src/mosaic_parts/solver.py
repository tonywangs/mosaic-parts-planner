"""Exact integer min-cost flow; no floating point or random tie breaking."""

from collections import Counter
from heapq import heappop, heappush

from .model import Color, InputError, MAX_CELLS, MAX_COLORS


def distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def assign(pixels: list[tuple[int, int, int]], colors: list[Color]) -> list[int]:
    """Return zero-based color indices minimizing total squared encoded-RGB error.

    Identical pixels share a supply node. Integral flows are expanded in row-major
    occurrence order, by ascending inventory index. Reverse residual edges allow
    earlier choices to be reassigned, unlike greedy nearest-available matching.
    """
    n = len(pixels)
    if not 1 <= n <= MAX_CELLS or not 1 <= len(colors) <= MAX_COLORS:
        raise InputError("assignment exceeds cell/color limits or is empty")
    if sum(c.available for c in colors) < n:
        raise InputError(f"insufficient inventory: need {n} tiles, have {sum(c.available for c in colors)}; add tiles or reduce the grid")
    counts = Counter(pixels)  # First-seen order is deterministic.
    targets = list(counts)
    m, k = len(targets), len(colors)
    source, sink = m + k, m + k + 1
    graph = [[] for _ in range(sink + 1)]

    def edge(u, v, capacity, cost):
        forward = [v, len(graph[v]), capacity, cost]
        reverse = [u, len(graph[u]), 0, -cost]
        graph[u].append(forward)
        graph[v].append(reverse)
        return forward

    links = []
    for i, pixel in enumerate(targets):
        edge(source, i, counts[pixel], 0)
        links.append([edge(i, m + j, counts[pixel], distance(pixel, color.rgb))
                      for j, color in enumerate(colors)])
    for j, color in enumerate(colors):
        edge(m + j, sink, min(n, color.available), 0)

    potential = [0] * len(graph)
    flow = 0
    infinity = 10**30
    while flow < n:
        dist = [infinity] * len(graph)
        previous = [None] * len(graph)
        dist[source] = 0
        queue = [(0, source)]
        while queue:
            d, u = heappop(queue)
            if d != dist[u]:
                continue
            for ei, (v, _, cap, cost) in enumerate(graph[u]):
                if cap <= 0:
                    continue
                candidate = d + cost + potential[u] - potential[v]
                if candidate < dist[v]:
                    dist[v] = candidate
                    previous[v] = (u, ei)
                    heappush(queue, (candidate, v))
        if previous[sink] is None:
            raise RuntimeError("internal error: feasible assignment has no augmenting path")
        for v, d in enumerate(dist):
            if d < infinity:
                potential[v] += d
        amount, v = n - flow, sink
        while v != source:
            u, ei = previous[v]
            amount = min(amount, graph[u][ei][2])
            v = u
        v = sink
        while v != source:
            u, ei = previous[v]
            e = graph[u][ei]
            e[2] -= amount
            graph[v][e[1]][2] += amount
            v = u
        flow += amount

    buckets = {}
    for i, pixel in enumerate(targets):
        values = []
        for j, e in enumerate(links[i]):
            values.extend([j] * (counts[pixel] - e[2]))
        assert len(values) == counts[pixel]
        buckets[pixel] = iter(values)
    result = [next(buckets[p]) for p in pixels]
    used = Counter(result)
    assert all(used[j] <= c.available for j, c in enumerate(colors))
    return result


def compare(pixels, colors, assigned):
    nearest = [min(range(len(colors)), key=lambda j: distance(p, colors[j].rgb)) for p in pixels]

    def metrics(placement):
        used = Counter(placement)
        error = sum(distance(p, colors[c].rgb) for p, c in zip(pixels, placement))
        excess = [max(0, used[j] - c.available) for j, c in enumerate(colors)]
        return {"total_squared_rgb_error": error,
                "mean_squared_rgb_error_per_channel": error / (3 * len(pixels)),
                "counts": [used[j] for j in range(len(colors))],
                "excess_by_color": excess, "excess_tiles": sum(excess),
                "colors_over_inventory": sum(v > 0 for v in excess)}

    return {"objective": "sum of squared distances in 8-bit encoded RGB (not perceptual)",
            "constrained": metrics(assigned), "nearest_unconstrained": metrics(nearest),
            "nearest_color_ids": [i + 1 for i in nearest]}
