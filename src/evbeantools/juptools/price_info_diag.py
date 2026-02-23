from __future__ import annotations
from pprint import pprint

from typing import Any

from ipywidgets import Widget
import ipywidgets as widgets

import plotly.graph_objects as go
import numpy as np

from schema import Schema, Optional, Or, SchemaError

from beancount.core import prices
from beancount.core.data import Transaction


# ----------------------------
# Core helpers
# ----------------------------

def get_posting_currencies(entries) -> set[str]:
    """Return all unique currencies used in Transaction postings."""
    currencies: set[str] = set()
    for entry in entries:
        if isinstance(entry, Transaction):
            for posting in entry.postings:
                currencies.add(posting.units.currency)
    return currencies


commodities_network_data_schema = Schema({
        Or(str, int): {                           # unique node ID can be string or int
            "name": str,
            Optional("connections"): [{
                "target": Or(str, int),           # target node ID
                Optional("hoverinfo"): str,
            }],
            Optional("directed_connections"): [{
                "target": Or(str, int),           # target node ID
                Optional("hoverinfo"): str,
            }],
            Optional("special"): bool,           # this node will be marked specially
            Optional("special1"): bool,          # this node will be marked specially1 (different from "special" for legend purposes)
            Optional("special2"): bool,          # this node will be marked specially2 (different from "special" and "special1" for legend purposes)
            Optional("hoverinfo"): str,          # hover text for the node
            Optional("special2_hoverinfo"): str, # hover text for the special2 marker (e.g. self-loop) if special2 is True
        }
    })

def build_prices_graph_data(price_map, currencies=None, special_nodes=None) -> dict:
    """Convert a Beancount PriceMap into a graph schema for visualization.
     - price_map: 
     Returns a dict, compliant with commodities_network_data_schema."""
     
    if currencies is None:
        currencies = []
    if special_nodes is None:
        special_nodes = []

    special_set = set(special_nodes)
    graph_data: dict = {}

    # isolated nodes first
    for curr in currencies:
        graph_data[curr] = {"name": curr, "connections": [], "special": curr in special_set}

    # edges from price_map
    for base, quote in price_map.keys():
        if base not in graph_data:
            graph_data[base] = {"name": base, "connections": [], "special": base in special_set}
        if quote not in graph_data:
            graph_data[quote] = {"name": quote, "connections": [], "special": quote in special_set}

        existing_targets = [c["target"] for c in graph_data[base]["connections"]]
        if quote not in existing_targets:
            graph_data[base]["connections"].append({"target": quote})

    return graph_data


# ----------------------------
# Plotly-as-widget (NO fig.show)
# ----------------------------

def make_prices_circular_network_widget(
    graph_data: dict,
    *,
    radius: float = 1.0,
    node_size: int = 35,
    label_normal: str = "Normal node",
    label_special: str = "Special node",
    label_special1: str = "Special1 node (thick border)",
    label_special2: str = "Special2 node (self-loop)",
    label_undirected: str = "Non-directional connection",
    label_directed: str = "Directed connection",
) -> Widget:
    """Return a Plotly FigureWidget showing a circular network.
     - graph_data: dict compliant with commodities_network_data_schema
     - radius: controls the size of the circular layout
     - node_size: marker size in pixels (default 35)
     - label_normal: legend text for default nodes
     - label_special: legend text for special nodes
     - label_special1: legend text for special1 nodes
     - label_special2: legend text for special2 nodes
     - label_undirected: legend text for undirected edges
     - label_directed: legend text for directed edges
     """
    
    pprint(graph_data)
    
    global commodities_network_data_schema 

    try:
        validated_data = commodities_network_data_schema.validate(graph_data)
    except SchemaError as e:
        return widgets.HTML(
            f"<pre style='color:#b00; white-space:pre-wrap;'>❌ Data Validation Error: {e}</pre>"
        )

    node_ids = list(validated_data.keys())
    n_nodes = len(node_ids)
    if n_nodes == 0:
        return widgets.HTML("<pre>⚠️ No nodes to display.</pre>")

    id_to_index = {node_id: i for i, node_id in enumerate(node_ids)}

    angles = np.linspace(0, 2 * np.pi, n_nodes, endpoint=False)
    x_nodes = radius * np.cos(angles)
    y_nodes = radius * np.sin(angles)

    # --- undirected edges ("connections") ---
    # Deduplicate: each pair (A,B) is drawn once.  If both sides carry
    # hoverinfo the texts are joined with " | ".
    seen_pairs: dict[tuple, str | None] = {}   # (min_id, max_id) → merged hover
    for source_id, attributes in validated_data.items():
        for conn in attributes.get("connections", []):
            target_id = conn["target"]
            if target_id not in id_to_index:
                continue
            pair_key = (min(source_id, target_id), max(source_id, target_id))
            hover = conn.get("hoverinfo")
            if pair_key not in seen_pairs:
                seen_pairs[pair_key] = hover
            elif hover is not None:
                prev = seen_pairs[pair_key]
                seen_pairs[pair_key] = f"{prev} | {hover}" if prev else hover

    # Split into edges without hover (batched) and edges with hover
    # (individual traces so Plotly can show tooltips).
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    hover_edges: list[tuple[float, float, float, float, str]] = []  # sx,sy,tx,ty,text

    for (a, b), hover in seen_pairs.items():
        a_idx, b_idx = id_to_index[a], id_to_index[b]
        sx, sy = float(x_nodes[a_idx]), float(y_nodes[a_idx])
        tx, ty = float(x_nodes[b_idx]), float(y_nodes[b_idx])
        if hover:
            hover_edges.append((sx, sy, tx, ty, hover))
        else:
            edge_x.extend([sx, tx, None])
            edge_y.extend([sy, ty, None])

    # --- directed edges ("directed_connections") ---
    # Collect (source_id, target_id, hoverinfo) tuples
    directed_edges: list[tuple] = []
    for source_id, attributes in validated_data.items():
        for conn in attributes.get("directed_connections", []):
            target_id = conn["target"]
            hover = conn.get("hoverinfo")
            if target_id in id_to_index:
                directed_edges.append((source_id, target_id, hover))

    COLOR_DEFAULT = "lightblue"
    COLOR_SPECIAL = "firebrick"
    COLOR_DIRECTED = "green"

    node_labels: list[str] = []
    node_hover: list[str] = []
    node_colors: list[str] = []
    node_border_widths: list[int] = []
    node_border_colors: list[str] = []
    for nid in node_ids:
        attr = validated_data[nid]
        node_labels.append(attr["name"])
        node_hover.append(attr.get("hoverinfo", attr["name"]))
        node_colors.append(COLOR_SPECIAL if attr.get("special", False) else COLOR_DEFAULT)
        if attr.get("special1", False):
            node_border_widths.append(4)
            node_border_colors.append("black")
        else:
            node_border_widths.append(2)
            node_border_colors.append("white")

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=1, color="#888"),
        hoverinfo="none",
        mode="lines",
    )

    node_trace = go.Scatter(
        x=x_nodes, y=y_nodes,
        mode="markers+text",
        text=node_labels,
        textposition="top center",
        hoverinfo="text",
        hovertext=node_hover,
        marker=dict(
            color=node_colors,
            size=node_size,
            line=dict(width=node_border_widths, color=node_border_colors),
        ),
    )

    # --- undirected edges with hover: each as a separate trace with
    #     an invisible midpoint marker so Plotly shows the tooltip.
    #     Built before the node trace so nodes render on top. ---
    hover_edge_traces: list[go.Scatter] = []
    for sx, sy, tx, ty, hover_txt in hover_edges:
        mx, my = (sx + tx) / 2, (sy + ty) / 2
        hover_edge_traces.append(go.Scatter(
            x=[sx, mx, tx], y=[sy, my, ty],
            mode="lines+markers",
            line=dict(width=1, color="#888"),
            marker=dict(size=[0, 8, 0], color="rgba(0,0,0,0)"),
            hoverinfo="text",
            hovertext=[None, hover_txt, None],
            showlegend=False,
        ))

    fig = go.Figure(
        data=[edge_trace] + hover_edge_traces + [node_trace],
        layout=go.Layout(
            title="Currency Price Map Network",
            showlegend=False,
            hovermode="closest",
            margin=dict(b=20, l=5, r=5, t=40),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, scaleanchor="x", scaleratio=1),
            plot_bgcolor="white",
        ),
    )

    # Approximate node marker radius in data-space units.
    # Default Plotly figure = 700 px wide, margins l=5 r=5 → plot area ~690 px.
    # The data range extends from roughly -(radius + 2*loop_radius) to
    # +(radius + 2*loop_radius) because self-loops stick out beyond the
    # circular layout.  Using the full visible span keeps arcs from
    # penetrating node circles when the plot auto-scales.
    loop_radius = 0.15 * radius
    data_span = 2 * (radius + 2 * loop_radius)
    node_data_radius = (node_size / 2) * (data_span / 690) * 1.35

    # --- self-loop for "special2" nodes (outer side of the virtual circuit) ---
    n_loop_pts = 80

    for nid in node_ids:
        if not validated_data[nid].get("special2", False):
            continue
        idx = id_to_index[nid]
        nx, ny = float(x_nodes[idx]), float(y_nodes[idx])
        node_angle = angles[idx]

        # Outward direction (from centre to node)
        ox, oy = np.cos(node_angle), np.sin(node_angle)

        # Centre of the loop circle, placed on the outer side of the node
        cx = nx + loop_radius * ox
        cy = ny + loop_radius * oy

        # Parametrise starting from the direction closest to the node so
        # that after trimming the remaining points form a single contiguous arc.
        inward_angle = node_angle + np.pi
        t = np.linspace(inward_angle, inward_angle + 2 * np.pi,
                        n_loop_pts, endpoint=False)
        lx = cx + loop_radius * np.cos(t)
        ly = cy + loop_radius * np.sin(t)

        # Trim points that fall inside the node marker
        dist_from_node = np.sqrt((lx - nx)**2 + (ly - ny)**2)
        keep = dist_from_node >= node_data_radius
        lx = lx[keep]
        ly = ly[keep]

        if len(lx) < 3:
            continue

        loop_hover = validated_data[nid].get("special2_hoverinfo")
        fig.add_trace(go.Scatter(
            x=lx.tolist(), y=ly.tolist(),
            mode="lines",
            line=dict(width=1.5, color=COLOR_DIRECTED),
            hoverinfo="text" if loop_hover else "none",
            hovertext=loop_hover,
            showlegend=False,
        ))

        # Arrowhead at the midpoint of the loop, pointing clockwise.
        # Place a triangle marker on the arc, rotated to match the
        # clockwise tangent so it sits on the curve (no chord effect).
        mid = len(lx) // 2
        prev_idx = min(len(lx) - 1, mid + 2)
        next_idx = max(0, mid - 2)
        tdx = float(lx[next_idx] - lx[prev_idx])
        tdy = float(ly[next_idx] - ly[prev_idx])
        tangent_angle = np.degrees(np.arctan2(tdy, tdx))
        # triangle-up points at +y (90°); marker.angle rotates CW
        marker_rotation = 90.0 - tangent_angle

        fig.add_trace(go.Scatter(
            x=[float(lx[mid])], y=[float(ly[mid])],
            mode="markers",
            marker=dict(
                symbol="triangle-up",
                size=12,
                color=COLOR_DIRECTED,
                angle=marker_rotation,
                line=dict(width=0),
            ),
            hoverinfo="none",
            showlegend=False,
        ))

    # --- add curved arrows for directed edges ---
    n_curve_pts = 60
    curve_bow = 0.1 * radius  # how far the arc bows away from the straight line

    for src_id, tgt_id, dir_hover in directed_edges:
        src_idx = id_to_index[src_id]
        tgt_idx = id_to_index[tgt_id]
        sx, sy = float(x_nodes[src_idx]), float(y_nodes[src_idx])
        tx, ty = float(x_nodes[tgt_idx]), float(y_nodes[tgt_idx])

        dx, dy = tx - sx, ty - sy
        length = np.sqrt(dx**2 + dy**2)
        if length == 0:
            continue

        # Perpendicular unit vector (points "left" of src→tgt).
        # When both A→B and B→A exist, the perpendicular naturally
        # flips direction with the edge, so both arcs bow to opposite
        # sides without any sign adjustment.
        perp_x, perp_y = -dy / length, dx / length

        # Quadratic Bézier control point (midpoint shifted perpendicular)
        mx = (sx + tx) / 2 + curve_bow * perp_x
        my = (sy + ty) / 2 + curve_bow * perp_y

        # Generate curve points: B(t) = (1-t)²·S + 2(1-t)t·M + t²·T
        t = np.linspace(0, 1, n_curve_pts)
        bx = (1 - t)**2 * sx + 2 * (1 - t) * t * mx + t**2 * tx
        by = (1 - t)**2 * sy + 2 * (1 - t) * t * my + t**2 * ty

        # Trim curve points that fall inside the source / target node
        # markers so the arc starts and ends at the circle edge.
        dist_from_src = np.sqrt((bx - sx)**2 + (by - sy)**2)
        dist_from_tgt = np.sqrt((bx - tx)**2 + (by - ty)**2)
        keep = (dist_from_src >= node_data_radius) & (dist_from_tgt >= node_data_radius)
        bx = bx[keep]
        by = by[keep]

        if len(bx) < 3:
            continue

        # Draw the curved line
        fig.add_trace(go.Scatter(
            x=bx.tolist(), y=by.tolist(),
            mode="lines",
            line=dict(width=1.5, color=COLOR_DIRECTED),
            hoverinfo="text" if dir_hover else "none",
            hovertext=dir_hover,
            showlegend=False,
        ))

        # Arrowhead at the midpoint of the curve so the direction is
        # clearly visible (rather than hidden near the node marker).
        mid = len(bx) // 2
        # Use points further apart so the annotation arrow is large
        # enough to be visible.
        arrow_back = max(0, mid - 4)
        arrow_front = min(len(bx) - 1, mid + 4)
        fig.add_annotation(
            x=float(bx[arrow_front]), y=float(by[arrow_front]),
            ax=float(bx[arrow_back]), ay=float(by[arrow_back]),
            xref="x", yref="y",
            axref="x", ayref="y",
            showarrow=True,
            arrowhead=3,
            arrowsize=1.5,
            arrowwidth=1.5,
            arrowcolor=COLOR_DIRECTED,
            standoff=0,
        )

    # Wrap in widgets.Output + fig.show() instead of returning a bare
    # FigureWidget.  FigureWidget relies on the Jupyter comm protocol,
    # which has timing issues in VS Code — the frontend JS may not be
    # ready when the comm message arrives, causing the diagram to
    # silently not render.  A plain Figure inside Output is reliable
    # everywhere (VS Code, JupyterLab, Colab).
    out = widgets.Output()
    with out:
        fig.show()

    # --- HTML legend ---
    legend_html = widgets.HTML(f"""
    <div style="display:flex; flex-wrap:wrap; gap:16px 32px; font:13px/1.6 sans-serif;
                padding:6px 10px; border:1px solid #ddd; border-radius:6px;
                background:#fafafa; margin-top:4px;">
      <div style="font-weight:600; width:100%; margin-bottom:2px;">Legend</div>

      <!-- Nodes -->
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:18px; height:18px; border-radius:50%;
                     background:{COLOR_DEFAULT}; border:2px solid white;"></span>
        {label_normal}
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:18px; height:18px; border-radius:50%;
                     background:{COLOR_SPECIAL}; border:2px solid white;"></span>
        {label_special}
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:18px; height:18px; border-radius:50%;
                     background:{COLOR_DEFAULT}; border:3px solid black;"></span>
        {label_special1}
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:24px; height:30px;">
          <svg viewBox="0 0 24 30" width="24" height="30" style="display:block;">
            <circle cx="12" cy="20" r="8" fill="{COLOR_DEFAULT}" stroke="white" stroke-width="1.5"/>
            <path d="M8,14 C4,0 20,0 16,14" fill="none" stroke="{COLOR_DIRECTED}" stroke-width="1.5"/>
            <polygon points="9,10 8,14 11.5,12" fill="{COLOR_DIRECTED}"/>
          </svg>
        </span>
        {label_special2}
      </div>

      <!-- Edges -->
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:28px; height:0; border-top:2px solid #888;"></span>
        {label_undirected}
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:28px; height:12px; position:relative;">
          <svg viewBox="0 0 28 12" width="28" height="12" style="display:block;">
            <path d="M0,6 Q14,0 28,6" fill="none" stroke="{COLOR_DIRECTED}" stroke-width="2"/>
            <polygon points="24,4 28,6 24,8" fill="{COLOR_DIRECTED}"/>
          </svg>
        </span>
        {label_directed}
      </div>
    </div>
    """)

    return widgets.VBox([out, legend_html])


def make_price_history_widget(
    price_map: dict,
    initial_pair: tuple[str, str] | None = None,
) -> Widget:
    """
    Cross-platform (Colab + Binder + VSCode + JupyterLab) price history widget.

    Key design choices for compatibility:
    - Uses widgets.Dropdown for selection.
    - Renders Plotly as a *regular* go.Figure displayed inside widgets.Output.
      (Avoids go.FigureWidget + comm-based updates, which are flaky in Colab.)
    - Converts dates to ISO strings for safe transport/rendering.
    """
    # --- Colab: enable widget manager if available (safe no-op elsewhere) ---
    # try:
    #     from google.colab import output as _colab_output  # type: ignore
    #     _colab_output.enable_custom_widget_manager()
    # except Exception:
    #     pass

    # --- Plotly renderer: prefer 'colab' if running in Colab, else leave default ---
    # try:
    #     import plotly.io as pio
    #     if "google.colab" in sys.modules:
    #         pio.renderers.default = "colab"
    # except Exception:
    #     pass

    available_pairs = sorted(price_map.keys(), key=lambda x: (x[0], x[1]))
    dropdown_width = "50%"

    if not available_pairs:
        pair_selector = widgets.Dropdown(
            options=[],
            description="Currency Pair:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width=dropdown_width),
            disabled=True,
        )
        msg = widgets.HTML("<pre>⚠️ PriceMap is empty.</pre>")
        return widgets.VBox([pair_selector, msg])

    if initial_pair is None:
        initial_pair = available_pairs[0]

    dropdown_options = [(f"{b} -> {q}", (b, q)) for b, q in available_pairs]

    pair_selector = widgets.Dropdown(
        options=dropdown_options,
        value=initial_pair,
        description="Currency Pair:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width=dropdown_width),
    )

    status = widgets.HTML("")
    out = widgets.Output()

    def _to_iso_date_strings(seq) -> list[str]:
        out_dates: list[str] = []
        for d in seq:
            if isinstance(d, str):
                out_dates.append(d)
            elif hasattr(d, "isoformat"):
                out_dates.append(d.isoformat())
            else:
                out_dates.append(str(d))
        return out_dates

    def _render(pair: tuple[str, str]) -> None:
        history = price_map.get(pair, [])

        with out:
            out.clear_output(wait=True)

            if not history:
                inverse = (pair[1], pair[0])
                hint = f" (inverse {inverse} exists)" if inverse in price_map else ""
                status.value = f"<pre>⚠️ No price history found for pair: {pair}.{hint}</pre>"
                return

            status.value = ""

            dates_raw = [item[0] for item in history]
            dates = _to_iso_date_strings(dates_raw)
            rates = [float(item[1]) for item in history]

            fig = go.Figure()
            fig.add_scatter(
                x=dates,
                y=rates,
                mode="lines+markers",
                name=f"{pair[0]}/{pair[1]}",
                marker=dict(size=4),
                line=dict(width=2),
            )
            fig.update_layout(
                title=f"Price History: {pair[0]} in {pair[1]}",
                xaxis=dict(title="Date", showgrid=True, gridcolor="#eee"),
                yaxis=dict(title=f"Price ({pair[1]})", showgrid=True, gridcolor="#eee", zeroline=False),
                plot_bgcolor="white",
                hovermode="x unified",
            )

            # IMPORTANT for Colab: display(fig) is more reliable than fig.show() inside Output
            # try:
            #     from IPython.display import display as _display
            #     _display(fig)
            # except Exception:
            #     fig.show()
            
            fig.show()

    def _on_pair_change(change):
        if change.get("name") == "value":
            _render(change["new"])

    pair_selector.observe(_on_pair_change, names="value")

    # initial draw
    _render(pair_selector.value)

    return widgets.VBox([pair_selector, status, out])


# ----------------------------
# Public API
# ----------------------------

def show_interactive_price_info(entries, options: dict[str, Any]) -> Widget:
    """
    Return a single widget that shows:
      1) circular price network (Plotly FigureWidget)
      2) interactive history explorer (dropdown + Plotly FigureWidget)
    """
    title_network = "Price Network"
    title_history = "Price History Explorer"
    radius = 1.0

    price_map = prices.build_price_map(entries)
    posting_currencies = list(get_posting_currencies(entries))

    operating_currencies = options.get("operating_currency", [])

    prices_graph_data = build_prices_graph_data(
        price_map,
        currencies=posting_currencies,
        special_nodes=operating_currencies,
    )

    network_widget = make_prices_circular_network_widget(prices_graph_data, radius=radius)
    
    # print(network_widget.data)
    
    
    history_widget = make_price_history_widget(price_map)

    header_network = widgets.HTML(f"<h3 style='margin:0 0 8px 0;'>{title_network}</h3>")
    header_history = widgets.HTML(f"<h3 style='margin:16px 0 8px 0;'>{title_history}</h3>")

    return widgets.VBox(
        [header_network, 
         network_widget, 
         header_history, 
         history_widget],
        layout=widgets.Layout(width="100%"),
    )
