import datetime
from decimal import Decimal
from collections import defaultdict
from collections.abc import Iterable

import matplotlib.colors as mcolors

import ipywidgets as widgets
from IPython.display import display

import plotly.graph_objects as go

from beancount.core.data import Transaction, Account
from beancount.core.account import root

from evbeantools.utils import  print_entries_to_string, print_errors_to_string

# -----------------------------------------------------------------------------
# Sankey diagram data preparation -------------------------------------------
#

# Data structure, which is used to collect information about postings, which is later user to prepare data for
# sankey diagram

PostingsData = dict[Account, Decimal]


def get_transaction_data(tansaction: Transaction, currency: str) -> PostingsData | None:
    """Function to get data about postings of a transaction for a specified currency.
    It returns a dictionary where keys are accounts and values are amounts for the specified currency.
    It also handles the case when there are several postings for the same account and currency, in this case it sums up
    the amounts for these postings.

    It raises errors if there conversions between the target currency and some other currency as this is shall
    not be the case in incoming data, as such data is impossible to display in sankey diagram,
    where every link should represent the same currency.
    """

    result = defaultdict(Decimal)

    for posting in tansaction.postings:
        if posting.units.currency == currency:
            if posting.cost and posting.cost.currency != currency:
                error_text = f"posting\n {posting} \n involves transfer of funds to / from  target currency {currency} and some other currency {posting.cost.currency}, which is not supported"
                raise ValueError(error_text)

            if posting.price and posting.price.currency != currency:
                error_text = f"posting\n {posting} \n involves transfer of funds to / from  target currency {currency} and some other currency {posting.price.currency}, which is not supported"
                raise ValueError(error_text)

            result[posting.account] += posting.units.number

        else:
            if posting.cost and posting.cost.currency == currency or posting.price and posting.price.currency == currency:
                error_text = f"posting\n {posting} \n involves transfer of funds to / from  target currency {currency} and some other currency {posting.units.currency}, which is not supported"
                raise ValueError(error_text)

    # summing up amounts for all accounts and the target currency

    total_across_accounts = sum(result.values())

    # TODO: check the tolerance
    # if total_across_accounts != Decimal("0"):
    #     raise RuntimeError(f"Something went wrong: total across accounts for transaction \n{print_entries_to_string([tansaction])}\n and currency {currency}"
    #                        f" is not equal to 0, but is equal to {total_across_accounts}")

    if len(result) > 0:
        return result


SourceToDestData = dict[tuple[Account, Account], Decimal]


def get_meshed_postings_data(postings_data: PostingsData) -> SourceToDestData:
    """Function to convert postings data into meshed source-to-destination data for sankey diagram.
    It takes postings data as input, where keys are accounts and values are amounts (negative for source accounts,
    positive for destination accounts).
    It returns a dictionary where keys are tuples of (source_account, destination_account) and values are amounts
    representing the flow from source to destination.
    The function distributes the amounts from source accounts to destination accounts proportionally.

    Parameters:
        postings_data: PostingsData - a dictionary where keys are accounts and values are amounts.
    Returns:
        SourceToDestData - a dictionary where keys are tuples of (source_account, destination_account) and values are amounts.
    """

    result = defaultdict(Decimal)

    from_postings_data = defaultdict(Decimal)
    to_postings_data = defaultdict(Decimal)

    for account, amount in postings_data.items():
        if amount < 0:
            from_postings_data[account] = -amount
        elif amount > 0:
            to_postings_data[account] = amount

    # Calculating total amount in to_postings_data
    total_to_amount = sum(to_postings_data.values())

    for from_account, from_amount in from_postings_data.items():
        for to_account, to_amount in to_postings_data.items():
            result[(from_account, to_account)] += from_amount * to_amount / total_to_amount

    return result


def get_meshed_postings_data_for_transaction(transaction: Transaction, currency: str) -> SourceToDestData | None:
    """Function to get meshed postings data for a transaction and a specified currency.
    It combines the functionality of get_transaction_data and get_meshed_postings_data functions.
    It returns a dictionary where keys are tuples of (source_account, destination_account) and values are amounts
    representing the flow from source to destination for the specified transaction and currency.

    Parameters:
        transaction: Transaction - a beancount Transaction object.
        currency: str - target currency for which the data is to be extracted.
    """

    postings_data = get_transaction_data(transaction, currency)

    if postings_data:
        meshed_data = get_meshed_postings_data(postings_data)
        return meshed_data
    else:
        return None


def add_dict_to_def_dic(def_dic: defaultdict, new_dic: dict):
    """
    Function to add values from new_dic to def_dic. It takes a defaultdict as def_dic and a regular dict as new_dic.
    For each key in new_dic, it adds the corresponding value to the value in def_dic for that key. If a key from new_dic
        does not exist in def_dic, it will be created with the value from new_dic.
        Parameters:
            def_dic: defaultdict - a defaultdict where values will be added to.
            new_dic: dict - a regular dictionary whose values will be added to def_dic.
        Returns:        defaultdict - the updated def_dic with values from new_dic added.
    """
    for key, value in new_dic.items():
        def_dic[key] += value
    return def_dic


def get_meshed_postings_data_for_entries(entries: Iterable,
                                         currency: str,
                                         start_date: datetime.date | None = None,
                                         end_date: datetime.date | None = None) -> SourceToDestData:
    """
    Function to get meshed postings data for a list of transactions and a specified currency.
    It returns a dictionary where keys are tuples of (source_account, destination_account) and values are amounts
    representing the flow from source to destination for the specified transactions and currency.

    Parameters:
        entries:  a list or any iterable of beancount entries.
        currency: str - target currency for which the data is to be extracted.
        start_date: - optional start date to filter postings. Postings with date less than start_date will be ignored.
        end_date:   - optional end date to filter postings. Postings with date greater than or equal to end_date will be
                      ignored.
    """

    result = defaultdict(Decimal)

    for entry in entries:

        if not isinstance(entry, Transaction):
            continue

        if start_date and entry.date < start_date:
            continue
        if end_date and entry.date >= end_date:
            continue

        meshed_data = get_meshed_postings_data_for_transaction(entry, currency)
        if meshed_data:
            result = add_dict_to_def_dic(result, meshed_data)

    return result


def shorten_account_name(account: Account,
                         income_len=100,
                         expenses_len=100,
                         equity_len=100,
                         assets_len=100,
                         liabilities_len=100) -> str:
    """
    Function to shorten an account name to a specified maximum length.
    If the account name is longer than the maximum length, it will be truncated and "..." will be added at the end.

    Parameters:
        account: Account - a beancount Account object whose name is to be shortened.
        income_len: int - maximum length for income account names.
        expenses_len: int - maximum length for expenses account names.
        equity_len: int - maximum length for equity account names.
        assets_len: int - maximum length for assets account names.
        liabilities_len: int - maximum length for liabilities account names.

    Returns:
        str - shortened account name if it was longer than max_len, otherwise the original account name.
    """
    account_type = root(1, account)

    if account_type == "Income":
        return root(income_len, account)
    elif account_type == "Expenses":
        return root(expenses_len, account)
    elif account_type == "Equity":
        return root(equity_len, account)
    elif account_type == "Assets":
        return root(assets_len, account)
    elif account_type == "Liabilities":
        return root(liabilities_len, account)
    else:
        return RuntimeError(f"Unknown account type {account_type} for account {account}")


def shorten_account_names(source_to_dest_data: SourceToDestData,
                          income_len=100,
                          expenses_len=100,
                          equity_len=100,
                          assets_len=100,
                          liabilities_len=100) -> SourceToDestData:
    """
    Function to shorten account names in source-to-destination data.
    It takes source-to-destination data as input, where keys are tuples of (source_account, destination_account) and values are amounts.
    It returns a new dictionary with shortened account names based on the specified lengths for different account types.
    Parameters:
        source_to_dest_data: SourceToDestData - a dictionary where keys are tuples of (source_account, destination_account) and values are amounts.
        income_len: int - maximum length for income account names.
        expenses_len: int - maximum length for expenses account names.
        equity_len: int - maximum length for equity account names.
        assets_len: int - maximum length for assets account names.
        liabilities_len: int - maximum length for liabilities account names.
    Returns:
        SourceToDestData - a new dictionary with shortened account names.
    """
    result = defaultdict(Decimal)

    for (source_account, dest_account), amount in source_to_dest_data.items():
        shortened_source_account = shorten_account_name(source_account, income_len, expenses_len, equity_len,
                                                        assets_len, liabilities_len)
        shortened_dest_account = shorten_account_name(dest_account, income_len, expenses_len, equity_len, assets_len,
                                                      liabilities_len)

        result[(shortened_source_account, shortened_dest_account)] += amount

    return result


def get_sankey_data_from_source_to_dest_data(source_to_dest_data: SourceToDestData) -> dict[str, list]:
    """
    Function to convert source-to-destination data into sankey diagram data format.
    It takes source-to-destination data as input, where keys are tuples of (source_account, destination_account) and values are amounts.
    It returns a dictionary with three keys: 'sources', 'destinations', and 'values', where:
        - 'source' is a list of source accounts,
        - 'target' is a list of destination accounts,
        - 'value' is a list of amounts corresponding to the flow from each source to each destination.
         - 'label' is a list of unique accounts (both sources and destinations) that will be used as labels in the sankey diagram.
    Parameters:
    source_to_dest_data: SourceToDestData - a dictionary where keys are tuples of (source_account, destination_account) and values are amounts.
    Returns:
        dict[str, list] - a dictionary with keys 'source', 'target', and 'value' for sankey diagram data.
    """

    sankey_data = {'source': [], 'target': [], 'value': [], 'label': [], 'color': []}

    assets_color = "blue"
    liabilities_color = "red"
    equity_color = "green"
    income_color = "orange"
    expenses_color = "purple"

    # getting unique accounts and creating a mapping from account to index
    unique_accounts = set()
    for source_account, dest_account in source_to_dest_data.keys():
        unique_accounts.add(source_account)
        unique_accounts.add(dest_account)

    account_to_index = {account: idx for idx, account in enumerate(unique_accounts)}

    for (source, target), value in source_to_dest_data.items():
        sankey_data['source'].append(account_to_index[source])
        sankey_data['target'].append(account_to_index[target])
        sankey_data['value'].append(float(value))

    sankey_data['label'] = list(unique_accounts)

    for account in sankey_data['label']:
        account_type = root(1, account)
        if account_type == "Assets":
            sankey_data['color'].append(assets_color)
        elif account_type == "Liabilities":
            sankey_data['color'].append(liabilities_color)
        elif account_type == "Equity":
            sankey_data['color'].append(equity_color)
        elif account_type == "Income":
            sankey_data['color'].append(income_color)
        elif account_type == "Expenses":
            sankey_data['color'].append(expenses_color)
        else:
            sankey_data['color'].append("grey")  # default color for unknown account types

    return sankey_data


def get_sankey_data_from_entries(entries: Iterable,
                                 currency: str,
                                 *,  # all parameters after * are keyword-only
                                 start_date: datetime.date | None = None,
                                 end_date: datetime.date | None = None,
                                 income_len=100,
                                 expenses_len=100,
                                 equity_len=100,
                                 assets_len=100,
                                 liabilities_len=100) -> dict[str, list]:
    source_to_dest_data = get_meshed_postings_data_for_entries(entries, currency, start_date, end_date)
    shortened_source_to_dest_data = shorten_account_names(source_to_dest_data,
                                                          income_len,
                                                          expenses_len,
                                                          equity_len,
                                                          assets_len,
                                                          liabilities_len)
    sankey_data = get_sankey_data_from_source_to_dest_data(shortened_source_to_dest_data)

    return sankey_data


def transparent(color: str, alpha: float = 0.4) -> str:
    """
    Convert any Matplotlib-compatible color into a Plotly/CSS rgba() string.
    """
    rgba = mcolors.to_rgba(color, alpha)  # (r,g,b,a) floats in [0,1]
    return f"rgba({int(rgba[0]*255)},{int(rgba[1]*255)},{int(rgba[2]*255)},{alpha})"


def get_ledger_dates_range(entries) -> tuple[datetime.date, datetime.date]:
    """
    Scans entries to find the earliest and latest transaction dates.
    """
    min_date = None
    max_date = None

    for entry in entries:
        if isinstance(entry, Transaction):
            if min_date is None or entry.date < min_date:
                min_date = entry.date
            if max_date is None or entry.date > max_date:
                max_date = entry.date

    if min_date is None or max_date is None:
        raise ValueError("No dated entries found to determine date range.")

    return min_date, max_date


def show_interactive_fin_flow_diag(entries: Iterable, currencies: list[str]) -> None:
    """
    Interactive Sankey + date controls in Jupyter.

    Improvement included:
      - a horizontal range bar (SelectionRangeSlider) to the right of Start/End pickers
      - left label = ledger min date, right label = ledger max date
      - moving either the DatePickers OR the bar keeps the other in sync
      - start/end markers are naturally shown as the slider handles
    """
    if not currencies:
        raise ValueError("currencies must be a non-empty list of currency codes/strings.")

    min_date, max_date = get_ledger_dates_range(entries)

    # ----------------------------
    # Controls (widgets)
    # ----------------------------

    currency_dd = widgets.Dropdown(
        options=currencies,
        value=currencies[0],
        description="Currency:",
        layout=widgets.Layout(width="260px"),
    )

    def _mk_slider(name: str, value: int, min_: int = 1, max_: int = 5, step: int = 1):
        return widgets.IntSlider(
            value=value,
            min=min_,
            max=max_,
            step=step,
            description=f"{name}:",
            continuous_update=False,
            readout=True,
            layout=widgets.Layout(width="520px"),
        )

    income_sl = _mk_slider("Income", 1, 1, 5)
    expenses_sl = _mk_slider("Expenses", 1, 1, 5)
    assets_sl = _mk_slider("Assets", 1, 1, 5)
    equity_sl = _mk_slider("Equity", 1, 1, 5)
    liabilities_sl = _mk_slider("Liabilities", 1, 1, 5)

    # Two DatePickers (fine-grained picking)
    start_dp = widgets.DatePicker(
        description="Start:",
        value=None,
        layout=widgets.Layout(width="220px"),
        min=min_date,
        max=max_date,
    )
    end_dp = widgets.DatePicker(
        description="End:",
        value=None,
        layout=widgets.Layout(width="220px"),
        min=min_date,
        max=max_date,
    )

    # Horizontal range bar that shows BOTH markers as draggable handles.
    # We build it on a dense list of dates so the handles snap cleanly.
    day_count = (max_date - min_date).days
    all_days = [min_date + datetime.timedelta(days=i) for i in range(day_count + 1)]

    range_bar = widgets.SelectionRangeSlider(
        options=all_days,                 # discrete dates
        value=(min_date, max_date),       # default full ledger range
        description="",                   # we'll show labels separately
        continuous_update=False,
        layout=widgets.Layout(width="520px"),
        readout=False,                    # we use Start/End DatePickers as readouts
    )

    # Labels at the ends of the bar
    min_lbl = widgets.HTML(f"<span style='font-size: 11px;'>{min_date.isoformat()}</span>")
    max_lbl = widgets.HTML(f"<span style='font-size: 11px; float:right'>{max_date.isoformat()}</span>")

    range_bar_box = widgets.VBox(
        [
            widgets.HBox([min_lbl, widgets.HTML("&nbsp;"), max_lbl], layout=widgets.Layout(justify_content="space-between")),
            range_bar,
        ],
        layout=widgets.Layout(width="520px"),
    )

    title = widgets.HTML("<b>Interactive financial flow Sankey</b>")
    out = widgets.Output()

    # ----------------------------
    # Sync logic: DatePickers <-> range_bar
    # ----------------------------
    _sync_guard = {"busy": False}

    def _coerce_to_bounds(d: datetime.date | None) -> datetime.date | None:
        """Clamp date to [min_date, max_date], leaving None untouched."""
        if d is None:
            return None
        if d < min_date:
            return min_date
        if d > max_date:
            return max_date
        return d

    def _sync_from_pickers(*_):
        """
        When user changes start_dp/end_dp, update range_bar.
        If either picker is None, we interpret it as full bound (min/max) for the bar.
        """
        if _sync_guard["busy"]:
            return
        _sync_guard["busy"] = True
        try:
            s = _coerce_to_bounds(start_dp.value)
            e = _coerce_to_bounds(end_dp.value)

            s_for_bar = s if s is not None else min_date
            e_for_bar = e if e is not None else max_date

            # Maintain ordering
            if s_for_bar > e_for_bar:
                # If user picked an invalid range, don't update bar; let render raise.
                _sync_guard["busy"] = False
                return

            range_bar.value = (s_for_bar, e_for_bar)
        finally:
            _sync_guard["busy"] = False

    def _sync_from_bar(change):
        """
        When user drags the range_bar handles, update start_dp/end_dp.
        We always set pickers to concrete dates (not None) because the bar is always concrete.
        """
        if _sync_guard["busy"]:
            return
        _sync_guard["busy"] = True
        try:
            s, e = change["new"]
            start_dp.value = s
            end_dp.value = e
        finally:
            _sync_guard["busy"] = False

    start_dp.observe(_sync_from_pickers, names="value")
    end_dp.observe(_sync_from_pickers, names="value")
    range_bar.observe(_sync_from_bar, names="value")

    # ----------------------------
    # Render callback
    # ----------------------------
    def _render(*_) -> None:
        with out:
            out.clear_output(wait=True)

            # We will pass the pickers' values through as-is (None allowed by your API)
            start_date = _coerce_to_bounds(start_dp.value)
            end_date = _coerce_to_bounds(end_dp.value)

            if start_date is not None and end_date is not None and start_date > end_date:
                raise ValueError(
                    f"start_date ({start_date}) must be <= end_date ({end_date})."
                )

            sankey_data = get_sankey_data_from_entries(
                entries,
                currency_dd.value,
                start_date=start_date,
                end_date=end_date,
                income_len=income_sl.value,
                expenses_len=expenses_sl.value,
                assets_len=assets_sl.value,
                equity_len=equity_sl.value,
                liabilities_len=liabilities_sl.value,
            )

            required = {"label", "color", "source", "target", "value"}
            missing = required - set(sankey_data.keys())
            if missing:
                raise KeyError(f"get_sankey_data_from_entries() missing keys: {sorted(missing)}")

            link_colors = [
                transparent(sankey_data["color"][s], alpha=0.35)
                for s in sankey_data["source"]
            ]

            fig = go.Figure(
                data=[
                    go.Sankey(
                        node=dict(
                            label=sankey_data["label"],
                            color=sankey_data["color"],
                            pad=15,
                            thickness=20,
                        ),
                        link=dict(
                            source=sankey_data["source"],
                            target=sankey_data["target"],
                            value=sankey_data["value"],
                            color=link_colors,
                        ),
                    )
                ]
            )

            date_part = []
            if start_date:
                date_part.append(f"from {start_date.isoformat()}")
            if end_date:
                date_part.append(f"to {end_date.isoformat()}")
            date_suffix = f" ({', '.join(date_part)})" if date_part else ""

            fig.update_layout(
                title_text=f"Financial flow — {currency_dd.value}{date_suffix}",
                height=600,
            )
            fig.show()

    # ----------------------------
    # Wire widget changes -> render
    # ----------------------------
    for w in (
        currency_dd,
        start_dp,
        end_dp,
        range_bar,   # changing the bar also triggers redraw
        income_sl,
        expenses_sl,
        assets_sl,
        equity_sl,
        liabilities_sl,
    ):
        w.observe(_render, names="value")

    # ----------------------------
    # Layout + display
    # ----------------------------
    controls = widgets.VBox(
        [
            title,
            widgets.HBox([currency_dd]),
            # Put the bar to the RIGHT of the date pickers
            widgets.HBox([start_dp, end_dp, range_bar_box]),
            income_sl,
            expenses_sl,
            assets_sl,
            equity_sl,
            liabilities_sl,
        ]
    )

    display(widgets.VBox([controls, out]))

    # Initialize bar/pickers consistency + initial render
    _sync_from_pickers()
    _render()
