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
        Or(str, int): {
            "name": str,
            "connections": [Or(str, int)],
            Optional("directed_connections"): [Or(str, int)],
            Optional("special"): bool,
            Optional("special1"): bool,
            Optional("special2"): bool,
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

        if quote not in graph_data[base]["connections"]:
            graph_data[base]["connections"].append(quote)

    return graph_data


# ----------------------------
# Plotly-as-widget (NO fig.show)
# ----------------------------

def make_prices_circular_network_widget(graph_data: dict, *, radius: float = 1.0, node_size: int = 35) -> Widget:
    """Return a Plotly FigureWidget showing a circular network.
     - graph_data: dict compliant with commodities_network_data_schema
     - radius: controls the size of the circular layout
     - node_size: marker size in pixels (default 25)
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
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []

    for source_id, attributes in validated_data.items():
        source_idx = id_to_index[source_id]
        for target_id in attributes["connections"]:
            if target_id in id_to_index:
                target_idx = id_to_index[target_id]
                edge_x.extend([float(x_nodes[source_idx]), float(x_nodes[target_idx]), None])
                edge_y.extend([float(y_nodes[source_idx]), float(y_nodes[target_idx]), None])

    # --- directed edges ("directed_connections") ---
    # Collect (source_id, target_id) pairs
    directed_edges: list[tuple] = []
    for source_id, attributes in validated_data.items():
        for target_id in attributes.get("directed_connections", []):
            if target_id in id_to_index:
                directed_edges.append((source_id, target_id))

    COLOR_DEFAULT = "lightblue"
    COLOR_SPECIAL = "firebrick"
    COLOR_DIRECTED = "green"

    node_labels: list[str] = []
    node_colors: list[str] = []
    node_border_widths: list[int] = []
    node_border_colors: list[str] = []
    for nid in node_ids:
        attr = validated_data[nid]
        node_labels.append(attr["name"])
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
        marker=dict(
            color=node_colors,
            size=node_size,
            line=dict(width=node_border_widths, color=node_border_colors),
        ),
    )

    fig = go.Figure(
        data=[edge_trace, node_trace],
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

    # --- black dot overlay for "special2" nodes ---
    dot_x = [float(x_nodes[id_to_index[nid]]) for nid in node_ids
             if validated_data[nid].get("special2", False)]
    dot_y = [float(y_nodes[id_to_index[nid]]) for nid in node_ids
             if validated_data[nid].get("special2", False)]
    if dot_x:
        fig.add_trace(go.Scatter(
            x=dot_x, y=dot_y,
            mode="markers",
            hoverinfo="none",
            showlegend=False,
            marker=dict(color="black", size=node_size * 0.35,
                        line=dict(width=0)),
        ))

    # --- add curved arrows for directed edges ---
    n_curve_pts = 60
    curve_bow = 0.15 * radius  # how far the arc bows away from the straight line

    # Approximate node marker radius in data-space units.
    # Default Plotly figure = 700 px wide, margins l=5 r=5 → plot area ~690 px.
    # The plot spans from -radius to +radius → 2·radius data units = 690 px.
    # marker radius in px = node_size/2, convert to data units, with a 1.15×
    # safety factor so the curve visibly clears the circle edge.
    node_data_radius = (node_size / 2) * (2 * radius / 690) * 1.15

    for src_id, tgt_id in directed_edges:
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
            hoverinfo="none",
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
            arrowsize=2,
            arrowwidth=2,
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
        Normal node
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:18px; height:18px; border-radius:50%;
                     background:{COLOR_SPECIAL}; border:2px solid white;"></span>
        Special node
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:18px; height:18px; border-radius:50%;
                     background:{COLOR_DEFAULT}; border:3px solid black;"></span>
        Special1 node (thick border)
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:18px; height:18px; border-radius:50%;
                     background:{COLOR_DEFAULT}; border:2px solid white; position:relative;">
          <span style="position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
                       width:7px; height:7px; border-radius:50%; background:black;"></span>
        </span>
        Special2 node (inner dot)
      </div>

      <!-- Edges -->
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:28px; height:0; border-top:2px solid #888;"></span>
        Non-directional connection
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <span style="display:inline-block; width:28px; height:12px; position:relative;">
          <svg viewBox="0 0 28 12" width="28" height="12" style="display:block;">
            <path d="M0,6 Q14,0 28,6" fill="none" stroke="{COLOR_DIRECTED}" stroke-width="2"/>
            <polygon points="24,4 28,6 24,8" fill="{COLOR_DIRECTED}"/>
          </svg>
        </span>
        Directed connection
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
