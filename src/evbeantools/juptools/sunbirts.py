from typing import Any, Dict, List, Tuple, Union
from collections import defaultdict

import pandas as pd

import plotly.graph_objects as go



# ---------------------------------------------------------------------------
# Config --------------------------------------------------------------------
# ---------------------------------------------------------------------------

_SEP = "==="   # ← centralised place to change the node‑ID separator


# ---------------------------------------------------------------------------
# Helpers -------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _safe_label(label: Any, parent_label: str) -> str:
    """Return a human‑readable label unique within its parent scope."""
    if label == "_":
        return f"{parent_label}_" if parent_label else "_"
    return str(label)


# ---------------------------------------------------------------------------
# Core builder --------------------------------------------------------------
# ---------------------------------------------------------------------------

def _aggregate_nodes(
    series: pd.Series,
    *,
    tolerate_negative_roots: bool = False,
) -> List[Dict[str, Any]]:  # noqa: C901 – complex but contained
    """Aggregate *series* values into Plotly‑ready nodes.

    The algorithm: build the full tree (truncating paths after the first "_"),
    then prune according to the *negative‑value policy*:

    * *Non‑root* negative → drop the entire sibling set (negative node plus its
      siblings) while retaining the parent.
    * *Root* negatives →
        * strict mode (``tolerate_negative_roots=False``): raise
          :class:`ValueError`.
        * lenient mode: silently drop the root(s) and their whole sub‑trees.
    """

    # ───────────────────────────── 1. normalise index ----------------------
    if not isinstance(series.index, pd.MultiIndex):
        series.index = pd.MultiIndex.from_arrays([series.index])

    # ───────────────────────────── 2. build full node pool -----------------
    node_pool: Dict[str, Dict[str, Any]] = {}

    for raw_path, raw_value in series.items():
        path = raw_path if isinstance(raw_path, tuple) else (raw_path,)

        parent_id = ""
        parent_label = ""
        saw_placeholder = False
        for depth, raw_label in enumerate(path):
            if saw_placeholder:
                break

            label = _safe_label(raw_label, parent_label)

            # deterministic current‑ID from visual labels
            parts: List[str] = []
            tmp_parent = ""
            for part in path[: depth + 1]:
                parts.append(_safe_label(part, tmp_parent))
                tmp_parent = parts[-1]
            curr_id = _SEP.join(parts)

            if curr_id not in node_pool:
                node_pool[curr_id] = {
                    "id": curr_id,
                    "label": label,
                    "parent": parent_id,
                    "value": 0.0,
                }
            node_pool[curr_id]["value"] += float(raw_value) if pd.notna(raw_value) else 0.0

            parent_id = curr_id
            parent_label = label
            if raw_label == "_":
                saw_placeholder = True

    # ───────────────────────────── 3. negate‑pruning -----------------------
    # separate negative nodes into roots vs non‑roots
    negative_nodes = [n for n in node_pool.values() if n["value"] < 0]
    root_negatives = [n for n in negative_nodes if n["parent"] == ""]
    nonroot_negatives = [n for n in negative_nodes if n["parent"] != ""]

    if root_negatives and not tolerate_negative_roots:
        names = ", ".join(n["label"] for n in root_negatives)
        raise ValueError(f"Root node(s) with negative value: {names}.")

    # Build parent → children map once
    children_map: Dict[str, List[str]] = defaultdict(list)
    for n in node_pool.values():
        children_map[n["parent"]].append(n["id"])

    to_drop: set[str] = set()

    # 3a) drop entire branches of root negatives (lenient mode)
    if tolerate_negative_roots:
        for neg in root_negatives:
            prefix = f"{neg['id']}{_SEP}"
            for node_id in list(node_pool):  # list() because we loop and modify
                if node_id == neg["id"] or node_id.startswith(prefix):
                    to_drop.add(node_id)

    # 3b) drop sibling sets of each non‑root negative
    for neg in nonroot_negatives:
        parent_id = neg["parent"]
        for child_id in children_map[parent_id]:
            prefix = f"{child_id}{_SEP}"
            for node_id in list(node_pool):
                if node_id == child_id or node_id.startswith(prefix):
                    to_drop.add(node_id)

    final_nodes = [n for n in node_pool.values() if n["id"] not in to_drop]
    return final_nodes


# ---------------------------------------------------------------------------
# Cosmetic pruning ----------------------------------------------------------
# ---------------------------------------------------------------------------

def prune_single_self_children(nodes: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Collapse placeholder children that are the only child of a parent."""
    children_map = defaultdict(list)
    for n in nodes:
        children_map[n["parent"]].append(n["id"])

    pruned = []
    for n in nodes:
        parent_id = n["parent"]
        if parent_id:
            only_child = len(children_map[parent_id]) == 1
            last_seg = parent_id.rsplit(_SEP, 1)[-1]
            expected = f"{parent_id}{_SEP}{last_seg}_"
            if only_child and n["id"] == expected:
                continue
        pruned.append(n)
    return pruned


# ---------------------------------------------------------------------------
# Public API ----------------------------------------------------------------
# ---------------------------------------------------------------------------

def get_sunburst_figure_from_pivot(
    df: pd.DataFrame,
    column_to_pick: Tuple[Any, ...],
    *,
    strict_mode: bool = True,
) -> go.Figure:
    """Build a Plotly *Sunburst* figure from pandas dataframe.
    The hierarchy of the sunburst diagram is derived from the index of the dataframe, 
    which is expected to be a multiindex.
    
    The values are taken from the column specified by *column_to_pick*.
    
    If data is structured in such a way, that total of the next level hierarchy is not equal to the parent,
    then the new  node with the name `parent_` is created, with the value equal to the difference between the parent and 
    the sum of the children.
    Example:
        Expenses:Misc         200 USD
        Expenses:Misc:Travel  100 USD
        
        In this case the `Misc` sector has a total of 300 USD, 
        but the sum of the children (`Misc:Travel`) is only 100 USD.
        
        In this case the sunburst sector `Misc` will be created with the value of 300 USD, and it will have 2 children:
          `Travel` with the value of 100 USD 
          `Misc_` with the value of 200 USD.
        
    
    If certain nodes are negative, then this node is dropped as well as all its children as well as all children of its 
    parent. See also usage of the strict_mode parameter for the situation, when the root node is negative.

    Parameters
    ----------
    df : dataframe with multiindex rows and columns
    
    column_to_pick: a column name.
    
    strict_mode : bool, default ``True``
        * ``True``  – strict mode: any negative‑valued root raises an error.
        * ``False`` – lenient mode: negative roots (and their branches) are
          simply excluded from the result.
    """

    try:
        series = df[column_to_pick].dropna()
    except KeyError as exc:
        raise KeyError(f"column_to_pick={column_to_pick} not found in df.columns") from exc

    series = series[series != 0]

    raw_nodes = _aggregate_nodes(
        series,
        tolerate_negative_roots=not strict_mode,
    )
    # print("-------raw_nodes----------")
    # pprint(raw_nodes, width=200)

    final_nodes = prune_single_self_children(raw_nodes)
    # print("-------final_nodes----------")
    # pprint(final_nodes, width=200)

    ids = [n["id"] for n in final_nodes]
    labels = [n["label"] for n in final_nodes]
    parents = [n["parent"] for n in final_nodes]
    values = [n["value"] for n in final_nodes]

    return go.Figure(
        go.Sunburst(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
        )
    )