import numpy as np
import math
import logging
from collections import deque

logger = logging.getLogger(__name__)

_DY = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
_DIST = [1.414,1.0,1.414,1.0,1.0,1.414,1.0,1.414]


def extract_stream_network(fdir: np.ndarray, facc: np.ndarray, threshold: float = None) -> np.ndarray:
    rows, cols = fdir.shape
    if threshold is None:
        threshold = max(facc.mean() * 3, 5)
    stream = facc > threshold
    stream &= fdir >= 0
    return stream


def find_stream_nodes(fdir: np.ndarray, stream: np.ndarray) -> list[dict]:
    rows, cols = fdir.shape
    nodes = []
    for r in range(1, rows-1):
        for c in range(1, cols-1):
            if not stream[r, c]:
                continue
            upstream = 0
            downstream = False
            for i, (dr, dc) in enumerate(_DY):
                nr, nc = r+dr, c+dc
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue
                if stream[nr, nc] and fdir[nr, nc] >= 0:
                    tr, tc = nr + _DY[fdir[nr,nc]][0], nc + _DY[fdir[nr,nc]][1]
                    if tr == r and tc == c:
                        upstream += 1
                if fdir[r, c] == i:
                    downstream = True
            if upstream >= 2 or (upstream >= 1 and not downstream):
                nodes.append({"row": r, "col": c, "upstream_count": upstream,
                              "is_outlet": not downstream})
    if not nodes:
        drain_r, drain_c = np.unravel_index(np.argmax(fdir), fdir.shape)
        nodes.append({"row": int(drain_r), "col": int(drain_c), "upstream_count": 0, "is_outlet": True})

    for n in nodes:
        n["lat_idx"] = n["row"]
        n["lon_idx"] = n["col"]
    return nodes


def assign_distributed_cn(dem: np.ndarray, fdir: np.ndarray) -> np.ndarray:
    rows, cols = dem.shape
    gy, gx = np.gradient(dem)
    slope_deg = np.arctan(np.sqrt(gx**2 + gy**2)) * 180 / math.pi

    cn = np.full((rows, cols), 75.0)

    cn[slope_deg < 3] = 82
    cn[(slope_deg >= 3) & (slope_deg < 8)] = 78
    cn[(slope_deg >= 8) & (slope_deg < 15)] = 72
    cn[(slope_deg >= 15) & (slope_deg < 25)] = 65
    cn[slope_deg >= 25] = 58

    local_min = dem < (dem.mean() - dem.std() * 0.5)
    cn[local_min] = np.minimum(cn[local_min] + 5, 92)

    return cn


def compute_travel_times(
    dem: np.ndarray, fdir: np.ndarray, facc: np.ndarray,
    cell_m: float, manning_n: float = 0.035,
) -> np.ndarray:
    rows, cols = fdir.shape
    travel_time = np.full((rows, cols), np.inf)

    indegree = np.zeros((rows, cols), dtype=np.int32)
    for r in range(rows):
        for c in range(cols):
            d = fdir[r, c]
            if 0 <= d < 8:
                dr, dc = _DY[d]
                nr, nc = r+dr, c+dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    indegree[nr, nc] += 1

    q = deque()
    for r in range(rows):
        for c in range(cols):
            if indegree[r, c] == 0:
                travel_time[r, c] = 0
                q.append((r, c))

    while q:
        r, c = q.popleft()
        d = fdir[r, c]
        if not (0 <= d < 8):
            continue
        dr, dc = _DY[d]
        nr, nc = r+dr, c+dc
        if not (0 <= nr < rows and 0 <= nc < cols):
            continue

        slope = max((dem[r, c] - dem[nr, nc]) / (cell_m * _DIST[d]), 0.001)
        flow_depth_est = max(math.sqrt(facc[r, c]) * 0.002, 0.01)
        v = (1.0 / manning_n) * (flow_depth_est ** (2.0/3.0)) * math.sqrt(slope)
        v = max(v, 0.1)
        seg_time = cell_m * _DIST[d] / v

        if travel_time[r, c] + seg_time < travel_time[nr, nc]:
            travel_time[nr, nc] = travel_time[r, c] + seg_time

        indegree[nr, nc] -= 1
        if indegree[nr, nc] == 0:
            q.append((nr, nc))

    travel_time[np.isinf(travel_time)] = 0
    return travel_time


def route_flow_time_area(
    dem: np.ndarray, fdir: np.ndarray, facc: np.ndarray,
    cn_grid: np.ndarray, travel_time: np.ndarray,
    rainfall_mm: float, duration_h: float, dt_min: float,
    cell_m: float,
) -> dict:
    rows, cols = dem.shape
    cell_area_m2 = cell_m * cell_m
    n_steps = int(duration_h * 60 / dt_min)
    dt = dt_min * 60

    s_grid = 25400.0 / cn_grid - 254
    ia_grid = 0.2 * s_grid
    excess = np.where(rainfall_mm > ia_grid,
                      (rainfall_mm - ia_grid)**2 / (rainfall_mm + 0.8 * s_grid),
                      0.0)

    max_tt = float(travel_time.max())
    if max_tt < 1:
        max_tt = duration_h * 3600
    n_bins = min(max(n_steps, 10), 30)
    bin_edges = np.linspace(0, max_tt, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    area_per_bin = np.zeros(n_bins)
    excess_per_bin = np.zeros(n_bins)
    for i in range(n_bins):
        mask = (travel_time >= bin_edges[i]) & (travel_time < bin_edges[i+1])
        area_per_bin[i] = mask.sum() * cell_area_m2
        excess_per_bin[i] = (excess[mask].sum() / 1000.0) * cell_area_m2

    total_excess_vol = excess_per_bin.sum()
    peak_step = n_steps // 3
    rain_factor = np.zeros(n_steps + 1)
    for s in range(n_steps + 1):
        if s < peak_step:
            rain_factor[s] = s / max(peak_step, 1)
        elif s < peak_step * 2:
            rain_factor[s] = 1.0
        else:
            rain_factor[s] = max(0, 1 - (s - peak_step*2) / max(n_steps - peak_step*2, 1))

    discharge = np.zeros(n_steps + 1)
    for t in range(n_steps + 1):
        q_t = 0
        for i in range(n_bins):
            lag_steps = int(bin_centers[i] / dt)
            rain_idx = t - lag_steps
            if 0 <= rain_idx <= n_steps:
                q_t += excess_per_bin[i] * rain_factor[rain_idx] / (duration_h * 3600)
        discharge[t] = q_t

    time_labels = [f"{s * dt_min / 60:.1f}h" for s in range(n_steps + 1)]
    peak_q = float(discharge.max())
    peak_q_idx = int(np.argmax(discharge))

    logger.info(f"[hydro_chain] Routed: total_excess={total_excess_vol:.0f}m3 peak_Q={peak_q:.1f}m3/s at {time_labels[peak_q_idx]}")

    return {
        "excess_rainfall_mm": excess.tolist(),
        "cn_grid_mean": round(float(cn_grid.mean()), 1),
        "cn_grid_range": [round(float(cn_grid.min()), 0), round(float(cn_grid.max()), 0)],
        "travel_time_max_s": round(max_tt, 0),
        "travel_time_mean_s": round(float(travel_time.mean()), 0),
        "time_area_histogram": (area_per_bin / area_per_bin.sum() * 100).round(2).tolist(),
        "discharge_cms": [round(q, 2) for q in discharge],
        "time_labels": time_labels,
        "peak_discharge_cms": round(peak_q, 1),
        "peak_discharge_time": time_labels[peak_q_idx],
        "total_runoff_volume_m3": round(total_excess_vol, 0),
        "n_subbasins": n_bins,
    }
