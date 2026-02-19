import datetime

import traitlets
import ipywidgets as widgets


class DateRangeWidget(widgets.HBox):
    """A composite date-range picker with two DatePickers and a SelectionRangeSlider.

    All three sub-widgets are kept in sync automatically: dragging the slider
    updates the pickers and vice-versa.

    Observable trait:
        value: ``tuple(datetime.date | None, datetime.date | None)`` —
            the currently selected ``(start_date, end_date)`` pair.
            Defaults to ``(None, None)`` (meaning "no constraint").

    Convenience properties:
        start_date: shortcut for ``value[0]``.
        end_date:   shortcut for ``value[1]``.

    Observe changes with the standard ipywidgets pattern::

        drw = DateRangeWidget(min_date, max_date)
        drw.observe(callback, names="value")

    Parameters:
        min_date: Earliest selectable date.
        max_date: Latest selectable date.
    """

    # Single observable trait — a tuple of (start_date, end_date)
    value = traitlets.Tuple(
        traitlets.Instance(datetime.date, allow_none=True),
        traitlets.Instance(datetime.date, allow_none=True),
        default_value=(None, None),
    )

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def start_date(self) -> datetime.date | None:
        """The currently selected start date (shortcut for ``value[0]``)."""
        return self.value[0]

    @start_date.setter
    def start_date(self, d: datetime.date | None):
        self.value = (d, self.value[1])

    @property
    def end_date(self) -> datetime.date | None:
        """The currently selected end date (shortcut for ``value[1]``)."""
        return self.value[1]

    @end_date.setter
    def end_date(self, d: datetime.date | None):
        self.value = (self.value[0], d)

    def __init__(self, min_date: datetime.date, max_date: datetime.date, **kwargs):
        self._min_date = min_date
        self._max_date = max_date
        self._sync_busy = False

        # --- DatePickers ---
        self._start_dp = widgets.DatePicker(
            description="Start:",
            value=None,
            layout=widgets.Layout(width="220px"),
            min=min_date,
            max=max_date,
        )
        self._end_dp = widgets.DatePicker(
            description="End:",
            value=None,
            layout=widgets.Layout(width="220px"),
            min=min_date,
            max=max_date,
        )

        # --- SelectionRangeSlider ---
        day_count = (max_date - min_date).days
        all_days = [min_date + datetime.timedelta(days=i) for i in range(day_count + 1)]

        self._range_bar = widgets.SelectionRangeSlider(
            options=all_days,
            value=(min_date, max_date),
            description="",
            continuous_update=False,
            layout=widgets.Layout(width="520px"),
            readout=False,
        )

        # --- Labels above the bar (selected range) ---
        self._sel_start_lbl = widgets.HTML(
            "<span style='font-size: 11px; color: #555;'>—</span>"
        )
        self._sel_end_lbl = widgets.HTML(
            "<span style='font-size: 11px; color: #555; float:right'>—</span>"
        )

        sel_row = widgets.HBox(
            [self._sel_start_lbl, widgets.HTML("&nbsp;"), self._sel_end_lbl],
            layout=widgets.Layout(justify_content="space-between"),
        )

        # --- Labels below the bar (absolute bounds) ---
        min_lbl = widgets.HTML(
            f"<span style='font-size: 11px; font-weight: bold;'>{min_date.isoformat()}</span>"
        )
        max_lbl = widgets.HTML(
            f"<span style='font-size: 11px; font-weight: bold; float:right'>{max_date.isoformat()}</span>"
        )

        bounds_row = widgets.HBox(
            [min_lbl, widgets.HTML("&nbsp;"), max_lbl],
            layout=widgets.Layout(justify_content="space-between"),
        )

        range_bar_box = widgets.VBox(
            [
                sel_row,
                self._range_bar,
                bounds_row,
            ],
            layout=widgets.Layout(width="520px"),
        )

        # --- Build HBox children ---
        super().__init__(
            children=[self._start_dp, self._end_dp, range_bar_box],
            **kwargs,
        )

        # --- Internal sync wiring ---
        self._start_dp.observe(self._sync_from_pickers, names="value")
        self._end_dp.observe(self._sync_from_pickers, names="value")
        self._range_bar.observe(self._sync_from_bar, names="value")

        # value trait changed programmatically → update pickers and bar
        self.observe(self._sync_from_value, names="value")

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _date_label(d: datetime.date | None) -> str:
        return d.isoformat() if d is not None else "—"

    def _update_sel_labels(self):
        """Refresh the 'selected start / end' labels above the bar."""
        s, e = self.value
        self._sel_start_lbl.value = (
            f"<span style='font-size: 11px; color: #555;'>{self._date_label(s)}</span>"
        )
        self._sel_end_lbl.value = (
            f"<span style='font-size: 11px; color: #555; float:right'>{self._date_label(e)}</span>"
        )

    def _coerce(self, d: datetime.date | None) -> datetime.date | None:
        """Clamp *d* to [min_date, max_date], leaving ``None`` untouched."""
        if d is None:
            return None
        if d < self._min_date:
            return self._min_date
        if d > self._max_date:
            return self._max_date
        return d

    def _sync_from_pickers(self, *_):
        """DatePickers changed → update range_bar + value trait."""
        if self._sync_busy:
            return
        self._sync_busy = True
        try:
            s = self._coerce(self._start_dp.value)
            e = self._coerce(self._end_dp.value)

            s_bar = s if s is not None else self._min_date
            e_bar = e if e is not None else self._max_date

            if s_bar > e_bar:
                return

            self._range_bar.value = (s_bar, e_bar)

            # Propagate to public trait
            self.value = (s, e)
            self._update_sel_labels()
        finally:
            self._sync_busy = False

    def _sync_from_bar(self, change):
        """Range bar changed → update DatePickers + value trait."""
        if self._sync_busy:
            return
        self._sync_busy = True
        try:
            s, e = change["new"]
            self._start_dp.value = s
            self._end_dp.value = e

            self.value = (s, e)
            self._update_sel_labels()
        finally:
            self._sync_busy = False

    def _sync_from_value(self, change):
        """value trait changed programmatically → update pickers and bar."""
        if self._sync_busy:
            return
        self._sync_busy = True
        try:
            s, e = change["new"]
            s = self._coerce(s)
            e = self._coerce(e)

            self._start_dp.value = s
            self._end_dp.value = e

            s_bar = s if s is not None else self._min_date
            e_bar = e if e is not None else self._max_date
            if s_bar <= e_bar:
                self._range_bar.value = (s_bar, e_bar)
            self._update_sel_labels()
        finally:
            self._sync_busy = False
