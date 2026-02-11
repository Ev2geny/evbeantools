from __future__ import annotations

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


def build_prices_graph_data(price_map, currencies=None, special_nodes=None) -> dict[str, dict[str, Any]]:
    """Convert a Beancount PriceMap into a graph schema for visualization."""
    if currencies is None:
        currencies = []
    if special_nodes is None:
        special_nodes = []

    special_set = set(special_nodes)
    graph_data: dict[str, dict[str, Any]] = {}

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

def make_prices_circular_network_widget(graph_data, radius: float = 1.0) -> Widget:
    """Return a Plotly FigureWidget showing a circular network."""
    network_schema = Schema({
        Or(str, int): {
            "name": str,
            "connections": [Or(str, int)],
            Optional("special"): bool,
        }
    })

    try:
        validated_data = network_schema.validate(graph_data)
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

    edge_x: list[float | None] = []
    edge_y: list[float | None] = []

    for source_id, attributes in validated_data.items():
        source_idx = id_to_index[source_id]
        for target_id in attributes["connections"]:
            if target_id in id_to_index:
                target_idx = id_to_index[target_id]
                edge_x.extend([float(x_nodes[source_idx]), float(x_nodes[target_idx]), None])
                edge_y.extend([float(y_nodes[source_idx]), float(y_nodes[target_idx]), None])

    COLOR_DEFAULT = "navy"
    COLOR_SPECIAL = "firebrick"

    node_labels: list[str] = []
    node_colors: list[str] = []
    for nid in node_ids:
        attr = validated_data[nid]
        node_labels.append(attr["name"])
        node_colors.append(COLOR_SPECIAL if attr.get("special", False) else COLOR_DEFAULT)

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
            size=25,
            line=dict(width=2, color="white"),
        ),
    )

    return go.FigureWidget(
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


def make_price_history_widget(price_map: dict, initial_pair: tuple[str, str] | None = None) -> Widget:
    """
    Return a widget with dropdown + Plotly FigureWidget for price history.
    Converts dates to ISO strings to keep comm messages JSON-serializable.
    """
    available_pairs = list(price_map.keys())
    available_pairs.sort(key=lambda x: (x[0], x[1]))

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
        empty_fig = go.FigureWidget()
        return widgets.VBox([pair_selector, msg, empty_fig])

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

    fig = go.FigureWidget()
    fig.add_scatter(mode="lines+markers", marker=dict(size=4), line=dict(width=2))
    status = widgets.HTML("")

    def _to_iso_date_strings(seq) -> list[str]:
        out: list[str] = []
        for d in seq:
            if isinstance(d, str):
                out.append(d)
            elif hasattr(d, "isoformat"):
                out.append(d.isoformat())
            else:
                out.append(str(d))
        return out

    def set_chart(pair: tuple[str, str]) -> None:
        history = price_map.get(pair, [])
        if not history:
            inverse = (pair[1], pair[0])
            hint = f" (inverse {inverse} exists)" if inverse in price_map else ""
            status.value = f"<pre>⚠️ No price history found for pair: {pair}.{hint}</pre>"

            with fig.batch_update():
                fig.data[0].x = []
                fig.data[0].y = []
                fig.layout.title = f"Price History: {pair[0]} in {pair[1]}"
                fig.layout.xaxis.title = "Date"
                fig.layout.yaxis.title = f"Price ({pair[1]})"
            return

        status.value = ""

        dates_raw = [item[0] for item in history]
        dates = _to_iso_date_strings(dates_raw)
        rates = [float(item[1]) for item in history]

        with fig.batch_update():
            fig.data[0].x = dates
            fig.data[0].y = rates
            fig.data[0].name = f"{pair[0]}/{pair[1]}"
            fig.layout.title = f"Price History: {pair[0]} in {pair[1]}"
            fig.layout.xaxis.title = "Date"
            fig.layout.yaxis.title = f"Price ({pair[1]})"
            fig.layout.plot_bgcolor = "white"
            fig.layout.hovermode = "x unified"
            fig.layout.xaxis.showgrid = True
            fig.layout.yaxis.showgrid = True
            fig.layout.yaxis.zeroline = False

    def on_pair_change(change):
        if change.get("name") == "value":
            set_chart(change["new"])

    pair_selector.observe(on_pair_change, names="value")
    set_chart(pair_selector.value)

    return widgets.VBox([pair_selector, status, fig])


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
    history_widget = make_price_history_widget(price_map)

    header_network = widgets.HTML(f"<h3 style='margin:0 0 8px 0;'>{title_network}</h3>")
    header_history = widgets.HTML(f"<h3 style='margin:16px 0 8px 0;'>{title_history}</h3>")

    return widgets.VBox(
        [header_network, network_widget, header_history, history_widget],
        layout=widgets.Layout(width="100%"),
    )
