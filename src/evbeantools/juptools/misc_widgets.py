import datetime

import ipywidgets as widgets


def get_date_range_picker_with_range_bar(
    min_date: datetime.date,
    max_date: datetime.date,
) -> tuple[widgets.HBox, widgets.DatePicker, widgets.DatePicker, widgets.SelectionRangeSlider]:
    """Create a date-range picker composed of two DatePickers and a SelectionRangeSlider.

    The three widgets are kept in sync automatically: dragging the slider
    updates the pickers and vice-versa.

    Parameters:
        min_date: Earliest selectable date.
        max_date: Latest selectable date.

    Returns:
        A tuple of ``(widget, start_dp, end_dp, range_bar)`` where
        *widget* is the ready-to-display ``HBox`` and the remaining items
        are the individual sub-widgets so the caller can read their values
        and attach additional observers.
    """
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

    # Initialize bar/pickers consistency
    _sync_from_pickers()

    widget = widgets.HBox([start_dp, end_dp, range_bar_box])
    return widget, start_dp, end_dp, range_bar
