"""
Set of tools to work with beancount in Jupyter notebooks environment
"""

from decimal import Decimal
import datetime
import re
from collections.abc import Iterable
from typing import Union, List, Tuple, Dict, Any, Optional, Callable, TypeVar, Generic, Type, cast, overload

import pandas as pd
import numpy as np

from beancount.core.prices import PriceMap, build_price_map
from beanquery.query import run_query


from evbeantools.summator import BeanSummator, InventoryAggregator


def convert_columns_to_float(df: pd.DataFrame) -> pd.DataFrame:
    """
    Checks types of the values in each column. If column contains Decimal, then converts this column to float
    This is done because pandas does not seems to work very well with Decimals

    Args:
        df (pd.DataFrame): initial dataframe

    Returns:
        pd.DataFrame: new modifyed dataframe
    """
    
    df = df.copy()
    for column_name in df:
        
        # print(f"Checking type of column with the name {column_name}")

        if not df[column_name].dtype == 'object':
            continue

        # https://stackoverflow.com/a/55754764/4432107
        list_of_type_in_column = [x for x in df[column_name].apply(type).unique()]

        if Decimal in list_of_type_in_column:
            df[column_name]=df[column_name].astype(float)
  
    return df


def add_total(df: pd.DataFrame,
              column_totals=True,
              row_totals=False,
              col_name_to_add_to: str | None = None,
              row_name_to_add_to: str | None = None) -> pd.DataFrame:
    """
    Adds totals to the dataframe
    Args:
        df (pd.DataFrame): input dataframe
        column_totals (bool): whether to add column totals
        row_totals (bool): whether to add row totals
        col_name_to_add_to (str): name of the column heading to add the 'Total' word to. If None, then 'Total' is added 
                                   as the the rows index
        row_name_to_add_to (str): name of the row to add row totals to. If None, then 'Total' is added 
                                   as the the column index
    """
    df = df.copy()
    
    if column_totals:
        # Compute the total row
        total_row = df.sum(numeric_only=True, axis=0)
        # For non-numeric columns, sum returns NaN; fill with empty strings
        total_row = total_row.fillna('')
        if col_name_to_add_to is None:
            # Set index to 'Total'
            total_row.name = 'Total'
            df = pd.concat([df, total_row.to_frame().T])
        else:
            # Set the value in col_name_to_add_to to 'Total'
            total_row[col_name_to_add_to] = 'Total'
            df = pd.concat([df, total_row.to_frame().T], ignore_index=True)
    
    if row_totals:
        # Compute the total column
        total_column = df.sum(numeric_only=True, axis=1)
        if row_name_to_add_to is None:
            # Add 'Total' as a new column
            df['Total'] = total_column
        else:
            # Add 'Total' column and set specific row to 'Total'
            df['Total'] = total_column
            df.loc[row_name_to_add_to, 'Total'] = 'Total'
    
    return df


def beanquery2df(entries: list, opts: dict,  query: str) -> pd.DataFrame:
    
    # print("Running my_run_query")
    
    # print(query)
    
    cols, rows = run_query(entries, opts, query, numberify=True)
    df = pd.DataFrame(rows, columns=[k[0] for k in cols])
    df = convert_columns_to_float(df)

    return df

