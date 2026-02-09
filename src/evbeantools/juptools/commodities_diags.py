# Define the functions, needed to explore the price information

from ipywidgets import Widget

def draw_prices_circular_network(graph_data, radius=1):
    """Generates and displays a network graph using a circular layout with schema validation.

    This function first validates the input `graph_data` against a strict schema.
    If valid, it maps node identifiers to geometric positions on a circle and 
    renders the topology using Plotly.

    Args:
        graph_data (dict): A dictionary definition of the graph.
            Expected Schema:
            {
                <Node ID (str or int)>: {
                    "name": str,
                    "connections": [str or int],
                    Optional("special"): bool
                }
            }
        radius (int or float, optional): The geometric radius of the node circle. 
            Defaults to 1.

    Returns:
        None: Displays the interactive Plotly figure.
    
    Raises:
        SchemaError: If `graph_data` does not match the required structure.
    """
    
    # --- 1. Define Schema & Validate ---
    # We define the structure we expect. 
    # Or(str, int) allows keys/IDs to be either strings or integers.
    network_schema = Schema({
        Or(str, int): {
            "name": str,
            "connections": [Or(str, int)],   # Must be a list of IDs (strs or ints)
            Optional("special"): bool        # Key is optional; value must be bool
        }
    })

    try:
        # validate() returns the data if successful, or raises SchemaError
        validated_data = network_schema.validate(graph_data)
    except SchemaError as e:
        print(f"❌ Data Validation Error: {e}")
        return

    # --- 2. Setup Geometry ---
    node_ids = list(validated_data.keys())
    n_nodes = len(node_ids)
    
    # Create a mapping from Node ID -> Index (0 to N-1)
    id_to_index = {node_id: i for i, node_id in enumerate(node_ids)}
    
    # Calculate angles and coordinates
    angles = np.linspace(0, 2 * np.pi, n_nodes, endpoint=False)
    x_nodes = radius * np.cos(angles)
    y_nodes = radius * np.sin(angles)
    
    # --- 3. Build Edges ---
    edge_x = []
    edge_y = []
    
    for source_id, attributes in validated_data.items():
        source_idx = id_to_index[source_id]
        
        # We can safely iterate because schema validation ensured 'connections' is a list
        for target_id in attributes['connections']:
            if target_id in id_to_index:
                target_idx = id_to_index[target_id]
                edge_x.extend([x_nodes[source_idx], x_nodes[target_idx], None])
                edge_y.extend([y_nodes[source_idx], y_nodes[target_idx], None])

    # --- 4. Build Node Attributes ---
    node_labels = []
    node_colors = []
    
    COLOR_DEFAULT = 'navy'
    COLOR_SPECIAL = 'firebrick'

    for nid in node_ids:
        attr = validated_data[nid]
        node_labels.append(attr['name'])
        
        # Schema validation ensures 'special' is bool if present, but it might be missing
        # so we use .get() with a default.
        if attr.get('special', False):
            node_colors.append(COLOR_SPECIAL)
        else:
            node_colors.append(COLOR_DEFAULT)

    # --- 5. Create Plotly Traces ---
    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=1, color='#888'),
        hoverinfo='none',
        mode='lines'
    )

    node_trace = go.Scatter(
        x=x_nodes, y=y_nodes,
        mode='markers+text',
        text=node_labels,
        textposition="top center",
        hoverinfo='text',
        marker=dict(
            color=node_colors,
            size=25,
            line=dict(width=2, color='white')
        )
    )

    # --- 6. Render ---
    fig = go.Figure(data=[edge_trace, node_trace],
                    layout=go.Layout(
                        title='Currency Price Map Network',
                        showlegend=False,
                        hovermode='closest',
                        margin=dict(b=20,l=5,r=5,t=40),
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, scaleanchor="x", scaleratio=1),
                        plot_bgcolor='white'
                    ))
    
    fig.show()

def build_prices_graph_data(price_map, currencies=None, special_nodes=None):
    """Converts a Beancount PriceMap into a graph schema for visualization.

    This function extracts all currency pairs from the PriceMap to build a 
    network topology. It identifies every currency as a node and every 
    pricing relationship (base -> quote) as a connection.
    
    If there are currencies provided in the `currencies` argument which are not
    present in the PriceMap, they will still be included as isolated nodes.

    Args:
        price_map (dict): A Beancount PriceMap object (or similar dict) where 
            keys are tuples of strings: (base_currency, quote_currency).
            Values are ignored for the graph structure.
        
        currencies (list of str, optional): A list of currency codes used in 
            all entries. Defaults to None. This list will mostl of the time intersect with the currencies found in the 
            price_map, but it can also contain some additional currencies, which are not present in the price_map, 
            but are still used in transactions.
        
        special_nodes (list of str, optional): A list of currency codes 
            (e.g., ['USD', 'EUR']) that should be flagged as 'special'. On a visualization, these nodes will be 
            highlighted differently to indicate their importance or centrality in the output data. 
            These are typically operating currencies 
            Defaults to None. 

    Returns:
        dict: A dictionary conforming to the graph_data schema:
            {
                "USD": {"name": "USD", "connections": ["EUR"], "special": True},
                "EUR": {"name": "EUR", "connections": ["USD"], "special": False},
                "ISO": {"name": "ISO", "connections": [], "special": False},
                ...
            }
    """
    if currencies is None:
        currencies = []
    
    if special_nodes is None:
        special_nodes = []
    
    # Use a set for O(1) lookups
    special_set = set(special_nodes)
    
    graph_data = {}

    # 1. Pre-populate with known currencies (Nodes from Ledger)
    # This ensures isolated nodes appear even if they have no price history.
    for curr in currencies:
        graph_data[curr] = {
            "name": curr,
            "connections": [],
            "special": curr in special_set
        }

    # 2. Iterate over every currency pair in the price map (Edges)
    for base, quote in price_map.keys():
        
        # Ensure Base exists (might not be in the 'currencies' list)
        if base not in graph_data:
            graph_data[base] = {
                "name": base,
                "connections": [],
                "special": base in special_set
            }

        # Ensure Quote exists
        if quote not in graph_data:
            graph_data[quote] = {
                "name": quote,
                "connections": [],
                "special": quote in special_set
            }

        # Add the connection (Base -> Quote) if not already present
        if quote not in graph_data[base]["connections"]:
            graph_data[base]["connections"].append(quote)

    return graph_data

def plot_price_history(price_map: dict, pair: tuple):
    """Visualizes the historical exchange rates for a specific currency pair.

    Args:
        price_map (dict): The Beancount PriceMap object.
        pair (tuple): A tuple of two strings representing the currency pair 
                      to display, e.g., ('AAPL', 'USD').

    Returns:
        None: Displays the interactive Plotly figure.
    """
    
    # 1. Retrieve Data
    # The PriceMap values are lists of (date, number) tuples.
    # If the pair doesn't exist, we default to an empty list.
    history = price_map.get(pair, [])

    if not history:
        print(f"⚠️ No price history found for pair: {pair}")
        # Check if the inverse exists and suggest it
        inverse = (pair[1], pair[0])
        if inverse in price_map:
            print(f"   (However, the inverse pair {inverse} was found.)")
        return

    # 2. Unpack Data for Plotting
    # We separate dates and rates. We also ensure rates are converted to floats
    # because Beancount uses Decimals, which Plotly can sometimes struggle with.
    dates = [item[0] for item in history]
    rates = [float(item[1]) for item in history]

    # 3. Create Plotly Trace
    trace = go.Scatter(
        x=dates,
        y=rates,
        mode='lines+markers',
        name=f"{pair[0]}/{pair[1]}",
        line=dict(color='royalblue', width=2),
        marker=dict(size=4)
    )

    # 4. Configure Layout
    layout = go.Layout(
        title=f'Price History: {pair[0]} in {pair[1]}',
        xaxis=dict(
            title='Date',
            showgrid=True,
            gridcolor='#eee'
        ),
        yaxis=dict(
            title=f'Price ({pair[1]})',
            showgrid=True,
            gridcolor='#eee',
            zeroline=False
        ),
        plot_bgcolor='white',
        hovermode='x unified' # Shows the value when you hover anywhere on the x-axis
    )

    # 5. Render
    fig = go.Figure(data=[trace], layout=layout)
    fig.show()
    
def show_interactive_prices_diag(price_map):
    """Creates a Jupyter widget to explore price history for all pairs in the map.

    Args:
        price_map (dict): The Beancount PriceMap object.
    """
    
    # 1. extract and Sort Options
    # We create a list of tuples: [("Label to show", Actual Value), ...]
    # Example: [("EUR -> USD", ("EUR", "USD")), ("AAPL -> USD", ("AAPL", "USD"))]
    available_pairs = list(price_map.keys())
    
    if not available_pairs:
        print("⚠️ PriceMap is empty.")
        return

    # Sort alphabetically for better UX
    available_pairs.sort(key=lambda x: (x[0], x[1]))
    
    dropdown_options = [(f"{base} -> {quote}", (base, quote)) for base, quote in available_pairs]

    # 2. Create Widgets
    # Dropdown for selection
    pair_selector = widgets.Dropdown(
        options=dropdown_options,
        value=available_pairs[0], # Default to first pair
        description='Currency Pair:',
        style={'description_width': 'initial'},
        layout=widgets.Layout(width='50%')
    )

    # Output area where the plot will be rendered
    plot_output = widgets.Output()

    # 3. Define Event Handler
    def on_pair_change(change):
        if change['type'] == 'change' and change['name'] == 'value':
            selected_pair = change['new']
            
            # Use the output widget context to capture the figure
            with plot_output:
                plot_output.clear_output(wait=True) # Clear previous chart
                plot_price_history(price_map, selected_pair)

    # Attach the handler
    pair_selector.observe(on_pair_change)

    # 4. Display Layout
    display(pair_selector, plot_output)

    # 5. Trigger Initial Draw
    # We manually trigger the draw for the default selected value
    with plot_output:
        plot_price_history(price_map, pair_selector.value)

    # --- Usage in Jupyter Notebook ---
    # interact_with_prices(price_map)
    
def get_posting_currencies(entries) -> set:
    """
    Scans entries and returns a set of all unique currencies used in Transaction postings.

    Args:
        entries (list): A list of Beancount directives (Transactions, Open, etc.).

    Returns:
        set: A set of unique currency strings (e.g., {'USD', 'EUR', 'AAPL'}).
    """
    currencies = set()
    
    for entry in entries:
        # We only care about entries that are Transactions
        if isinstance(entry, Transaction):
            for posting in entry.postings:
                # posting.units is an Amount(number, currency)
                currencies.add(posting.units.currency)
                
    return currencies

from ipywidgets import Widget
from requests import options

def show_interactive_price_info(entries, options) -> Widget:
    """
    Displays (1) the circular price network and (2) an interactive price-history explorer
    together (no collapsing), in a single composite widget.
    """
    
    title_network = "Price Network"
    title_history = "Price History Explorer"
    radius = 1.0
    dropdown_width = "50%"
    
    opts = dict(options or {})

    # --- Build data ---
    price_map = prices.build_price_map(entries)
    posting_currencies = list(get_posting_currencies(entries))

    operating_currencies = options["operating_currency"]

    prices_graph_data = build_prices_graph_data(
        price_map,
        currencies=posting_currencies,
        special_nodes=operating_currencies,
    )
    

    # --- Output panes ---
    network_out = widgets.Output()
    history_out = widgets.Output()

    # --- Render network (top) ---
    with network_out:
        network_out.clear_output(wait=True)
        try:
            draw_prices_circular_network(prices_graph_data, radius=radius)
        except Exception as e:
            print(f"⚠️ Failed to render network graph: {e}")

    # --- Build history explorer (bottom) ---
    available_pairs = list(price_map.keys())
    available_pairs.sort(key=lambda x: (x[0], x[1]))

    if not available_pairs:
        pair_selector = widgets.Dropdown(
            options=[],
            description="Currency Pair:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width=dropdown_width),
            disabled=True,
        )
        plot_out = widgets.Output()
        with plot_out:
            print("⚠️ PriceMap is empty.")
    else:
        dropdown_options = [(f"{b} -> {q}", (b, q)) for b, q in available_pairs]

        pair_selector = widgets.Dropdown(
            options=dropdown_options,
            value=available_pairs[0],
            description="Currency Pair:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width=dropdown_width),
        )

        plot_out = widgets.Output()

        def redraw(pair):
            with plot_out:
                plot_out.clear_output(wait=True)
                plot_price_history(price_map, pair)

        def on_pair_change(change):
            if change.get("type") == "change" and change.get("name") == "value":
                redraw(change["new"])

        pair_selector.observe(on_pair_change, names="value")
        redraw(pair_selector.value)

    # --- Compose: both visible at once ---
    header_network = widgets.HTML(f"<h3 style='margin:0 0 8px 0;'>{title_network}</h3>")
    header_history = widgets.HTML(f"<h3 style='margin:16px 0 8px 0;'>{title_history}</h3>")

    root = widgets.VBox(
        [
            header_network,
            network_out,
            header_history,
            pair_selector,
            plot_out,
        ],
        layout=widgets.Layout(width="100%"),
    )

    # return root
    return root






