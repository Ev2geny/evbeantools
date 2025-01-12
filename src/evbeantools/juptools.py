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


def get_matching_columns(df: pd.DataFrame, regex: str) -> list[str]:
    """
    Analyzes dataframe and returns a list of columns, which names match the given regex

    """
    matching_columns = df.filter(regex=regex).columns.tolist()
    return matching_columns

# this is not used at the moment as replaced by get_bean_pivot, left here for historical reasons
def get_my_pivot(df, column='year',rows=None, sort_by=None) -> pd.DataFrame:
    df = df.copy()
    n_levels = df["account"].str.count(":").max() + 1
    cols = [f"acc_L{k}" for k in range(n_levels)]
    df[cols] = df["account"].str.split(':', n=n_levels - 1, expand=True)

    # Replacing in acc_LN columns None with "_", otherwise pivot does not work well
    for col_name in cols:
        df[col_name] = df[col_name].replace(to_replace=[None], value="_")

    first_col_with_nunique_acc = None
    
    for col_name in cols:
        if df[col_name].nunique() >1:
            first_col_with_nunique_acc = col_name
            # print(f"first_col_with_nunique_acc = {first_col_with_nunique_acc}")
            break
    
    if rows:
        index = rows
    else:
        index = first_col_with_nunique_acc
        
    # print(f"df before pivotting")
    # print(df)

    values_columns = get_matching_columns(df, regex=r"cost.*")
    
    # print(f"values_columns = {values_columns}")

    df_pivot = df.pivot_table(index=index, values=values_columns, dropna=False, columns=[column], aggfunc='sum').fillna(0).reset_index()
    # df_pivot = df.pivot_table(index=index, dropna=False, columns=[column], aggfunc='sum').fillna(0).reset_index()
    if sort_by:
        df_pivot = df_pivot.sort_values(by=sort_by, ascending=False)
    
    return df_pivot


def get_date_for_query(date: str | datetime.datetime | datetime.date | int)->str:
    """
    Converts a given date in various formats to a standardized string format.

    This function accepts a date input in various formats such as string, datetime object, date object, 
    or an integer representing a year. It returns the date in a standardized 'YYYY-MM-DD' string format.
    It raises a ValueError if the input date does not conform to expected formats or values.

    Args:
        date (Union[str, datetime.datetime, datetime.date, int]): 
            The date to be converted. Can be a string in 'YYYY-MM-DD' format, a datetime.datetime or 
            datetime.date object, or an integer representing a year.

    Returns:
        str: The date in 'YYYY-MM-DD' string format.

    Raises:
        ValueError: If the date string is not in 'YYYY-MM-DD' format, if the date integer is less than 1000, 
                    or if the input is not of a recognized type.

    Examples:
        >>> get_date_for_query("2023-11-26")
        '2023-11-26'
        >>> get_date_for_query(datetime.datetime(2023, 11, 26))
        '2023-11-26'
        >>> get_date_for_query(datetime.date(2023, 11, 26))
        '2023-11-26'
        >>> get_date_for_query(2023)
        '2023-12-31'
    """
    
    if isinstance(date, str):
        query_date = date
        res=re.match(r"^\d{4}-\d{2}-\d{2}$", query_date)
        if not res:
            raise ValueError(f"date must be in the format YYYY-MM-DD, not {date}")
    elif isinstance(date, datetime.datetime):
        query_date = date.strftime("%Y-%m-%d")
    elif isinstance(date, datetime.date):
        query_date = date.strftime("%Y-%m-%d")
    elif isinstance(date, int):
        if date < 1000:
            raise ValueError(f"date cannot be an integer less than 1000. Currently it is {date}")
        query_date = f"{date}-12-31"
    else:
        raise ValueError(f"date must be a string, datetime, date, interger of the yer not {type(date)}")
    return query_date


def get_net_worth(entries, opts, date: int | str | datetime.date | datetime.datetime, currency: str) -> pd.DataFrame:
    target_date = get_date_for_query(date)
    
    # print(f"query_date = {query_date}")
    
    query = f"""
    SELECT account, convert(SUM(position),'{currency}',{target_date}) as amount
    where date <= {target_date} AND account ~ 'Assets|Liabilities'
    """
    # print("******** query *********")
    # print(query)
    
    df = beanquery2df(entries, opts, query)
    
    df['q_date'] = target_date
    # print(df)
    return df


def inv_agg_to_df(inv_agg: InventoryAggregator,
                  accounts_column_name='account',
                  amount_column_name="amount") -> pd.DataFrame:
        """ 
        Converts an InventoryAggregator object to a pandas DataFrame
        Dataframe will have one column for Account with the name accounts_column_name, 
        Plus one column for every currency in InventoryAggregator
        Columns for currencies will be named like "{amount_column_name} ({CURR})", where CURR is a currency
        
        Parameters:
            inv_agg
            accounts_column_name (str): Name of the column for the amounts, which will be formed like 
                f"amount_column_name ({CURR})", where CURR is a curreny, of the inventory
            amount_column_name
            
        Returns:
            pd.DataFrame: DataFrame with columns 'Account' and 'Inventory'
        """
        
        # getting list of all currencies in the InventoryAggregator object
        currencies = inv_agg.currencies()
        
        rows_lst = []
        
        for account, inv in inv_agg.items():
            row = []
            row.append(account)
            for currency in currencies:
                row.append(inv.get_currency_units(currency).number)
            rows_lst.append(row)
            
        columns = [accounts_column_name] + [f"{amount_column_name} ({currency})" for currency in currencies]
        
        return pd.DataFrame(rows_lst, columns=columns)
    
    
def get_net_worths(entries, opts, dates: Iterable, target_currency: str):
    
    bean_summator = BeanSummator(entries, opts, "Assets|Liabilities")
    
    # building price map from entries

    price_map = build_price_map(entries)
    
    dates_intern = list(dates)
    # print(f"dates_intern = {dates_intern}")
    # date = dates_intern[0]
    # print(f"running get_net_worth for date {date}")
    # net_worth = get_net_worth(entries, opts, date, currency)
    
    net_worths = pd.DataFrame()
    
    # print(f"net_worth = {net_worth}")
    
    for date in dates_intern:
        # net_worth = net_worth.append(get_net_worth(entries, errors, opts, date, currency), ignore_index=True)
        net_worth: InventoryAggregator = bean_summator.sum_till_date(date).convert(target_currency, price_map, date)
        net_worth_df: pd.DataFrame = inv_agg_to_df(net_worth)
        # print('net_worth')
        # print(net_worth)
        net_worth_df['q_date'] = date
        net_worths=pd.concat([net_worths, net_worth_df], ignore_index=True)
        
    # pivot=get_my_pivot(net_worth, column='q_date', rows='account')
    
    # print(net_worth.head())
    
    net_worths = convert_columns_to_float(net_worths)
    
    # print('net_worths')
    # print(net_worths)
    
    pivot=get_bean_pivot(net_worths, column='q_date',max_row_levels=10,repeat_row_labels=True)
    
    return pivot


def check_presence_of_column_in_dataframe(df:pd.DataFrame, column):
    """
    Verifies whether a specified column or a column matching a given pattern exists within a pandas DataFrame. 
    This function supports both standard and MultiIndex column DataFrames. For MultiIndex DataFrames, it provides 
    additional functionality to suggest a possible matching column if the specified column name does not directly 
    match but is similar to an element within the MultiIndex columns.

    Parameters:
    - df (pd.DataFrame): The DataFrame to check for the specified column.
    - column (str or tuple): The column name or pattern to check for. This should be a string for standard DataFrame 
      columns or a tuple for MultiIndex DataFrame columns.

    Returns:
    - None: The function returns None if the specified column exists within the DataFrame, indicating success.

    Raises:
    - ValueError: If the specified column does not exist within the DataFrame. The error message details whether the 
      DataFrame has MultiIndex columns and the column was expected to be a tuple but was not, including a suggestion 
      for a possibly intended column if a close match is found within the MultiIndex columns. If no close match is 
      found, or the DataFrame does not use MultiIndex columns, a generic error message indicating the absence of the 
      specified column is raised.

    Notes:
    - For MultiIndex columns, the function attempts to identify a close match by searching each level of the MultiIndex 
      for the specified column name or a pattern match. If a potential match is found, it suggests this match in the 
      raised ValueError.
    - This function is useful for data validation and error handling when working with DataFrames of varying complexity,
      ensuring that operations relying on specific columns can proceed safely.
    """
    
    columns=df.columns
    
    # print('columns.values')
    # print(list(columns.values))
    
    if column in list(columns.values):
        return 
    
    # checking whether columns is a multiindex
    if isinstance(columns, pd.MultiIndex) and not isinstance(column, tuple):
        
        possibly_meant_column_to_pick=None
        for multiindex_value in columns.values:
            for element in multiindex_value:
                if element == column or re.match(str(column), str(element)):
                    possibly_meant_column_to_pick = multiindex_value
                    break
        error_message = f"columns of the input dataframe is a MultiIndex object \n\n {columns} \n\n but the parameter 'column_to_pick' \n\n {column} \n\n is not a Tupe as expected in this case"
        
        if possibly_meant_column_to_pick:
            error_message+=f"\n Did you mean to pick the following column? \n {possibly_meant_column_to_pick}"        
                
        raise ValueError(error_message)
    
    raise ValueError(f"column = {column} is not present in the dataframe columns = {columns}")


def get_bean_pivot(df,
                   column: str = 'year',
                   max_row_levels=1,
                   sort_by=None,
                   ascending=False,
                   drop_identical_row_levels=True,
                   repeat_row_labels=False,
                   values: str = "amount") -> pd.DataFrame:
    """
    Generates a pivot table from a given DataFrame based on specified parameters, primarily focusing on financial data.
    
    This function manipulates the input DataFrame to create a pivot table that aggregates data by accounts, splitting 
    account hierarchies into multiple levels and summing up the values under a specified column. It offers options to 
    sort the results, limit the depth of row level hierarchies, and repeat row labels for clarity.
    
    Parameters:
    - df : The input DataFrame containing the data to be pivoted.
    - column (str, optional): The column name to use as the pivot table columns. Defaults to 'year'.
    - max_row_levels (int, optional): The maximum number of hierarchical levels to include in the pivot table rows. Defaults to 1.
    - sort_by (tuple, optional): A tuple specifying the column(s) to sort the pivot table by. Defaults to None, which means no sorting.
    - drop_identical_row_levels (bool, optional): Whether to drop initial row levels if they are identical across the dataset,
      to simplify the pivot table. Defaults to True.
    - repeat_row_labels (bool, optional): Whether to repeat row labels when the pivot table is reset. Useful for clarity in
      the final table. Defaults to False.
    - values (str, optional): The column name to aggregate in the pivot table, specified as a regex pattern. Defaults to "amount".
    
    Returns:
    pd.DataFrame: A pivot table generated from the input DataFrame according to the specified parameters.
    
    Raises:
    ValueError: If no columns in the DataFrame match the regex specified in the 'values' parameter.
    
    Notes:
    The function assumes the presence of an 'account' column in the input DataFrame, which is used to split the account
    information into hierarchical levels for the pivot table rows. The values in the 'account' column are expected to be
    delimited by colons (:).
    """
    df = df.copy()
    
    values_columns = get_matching_columns(df, regex=str(values))
    if len(values_columns) == 0:
        raise ValueError(f"no columns found matching the regex {values}")
    
    # checking, that dtype of values_columns is numeric
    for col in values_columns:
        if not np.issubdtype(df[col].dtype, np.number):
            raise ValueError(f"column {column} is not numeric")
    
    # Splitting the 'account' column into several columns based on the colon delimiter
    n_levels = df["account"].str.count(":").max() + 1
    col_names = [f"acc_L{k}" for k in range(n_levels)]
    df[col_names] = df["account"].str.split(':', n=n_levels - 1, expand=True)

    # Replacing in acc_LN columns None with "_", otherwise pivot does not work well
    for col_name in col_names:
        df[col_name] = df[col_name].replace(to_replace=[None], value="_")

    
    if drop_identical_row_levels:
        for col_name in col_names:
            if df[col_name].nunique() > 1:
                break
                
            df.drop(columns=[col_name],inplace=True)
            col_names=col_names[1:]
        
    if max_row_levels:
        col_names = col_names[:min(max_row_levels, len(col_names))]
        
    # print(col_names)
    
    # print(df)

    # df_pivot1 = df.pivot_table(index=col_names, values='amount (EUR)', dropna=True, columns=[column], aggfunc='sum').fillna(0)
    # print(df_pivot1)
    # print(df_pivot1.index)
    # print(df_pivot1.columns)
    
    # print('**********************************')
    
    df_pivot = df.pivot_table(index=col_names, values=values_columns, dropna=True, columns=[column], aggfunc='sum').fillna(0)
    # print(df_pivot)
    # print(df_pivot.index)
    # print(df_pivot.columns)
    
    if repeat_row_labels:
        df_pivot = df_pivot.reset_index()
    
    # sort_by = ('amount (EUR)', 2020)
    
    if sort_by:
        
        try:
            df_pivot = df_pivot.sort_values(by=sort_by, ascending=ascending)
        except Exception as e:
            raise RuntimeError(f"An exception is raised when trying to sort pivot table by {sort_by}.\n"\
                "Try calling the function with the 'sort_by' parameter and then use DataFrame.columns command to see the correct naming for columns") from e
    
    
    return df_pivot


def generate_unique_el(el:Any, existing_els:set, uniquelizetor:str='+')->str:
    if el not in existing_els:
        raise ValueError(f"el = {el} is already not in existing_els = {existing_els}")
    
    new_el = str(el)+uniquelizetor
    
    if new_el in existing_els:
        new_el = generate_unique_el(new_el, existing_els)
        
    return new_el


def uniquelize_multiindex_levels(df:pd.DataFrame, empty_value_el='_', uniquelizetor:str = "+")->pd.DataFrame:
    
    if empty_value_el == uniquelizetor:
        raise ValueError(f"empty_value_el = {empty_value_el} cannot be equal to uniquelizetor = {uniquelizetor}")
    
    df = df.copy()
    index = df.index
    index_names = index.names
    flat_index_list = index.to_flat_index().tolist()
    # print(flat_index_list)
    flat_index_list_trasposed = list(map(list, zip(*flat_index_list)))
    # print(flat_index_list_trasposed)
    # creating a set of already seen elements from the first element of array, which represents the first column of the multiindex
    # As this is the 1st column of the multiindex, they all will be unique
    already_seen_els = set(flat_index_list_trasposed[0])
    qnt_rows = len(flat_index_list_trasposed)
    qnt_coumns = len(flat_index_list_trasposed[0])
    for row_n in range(1,qnt_rows):
        # print("*"*20)
        # print(f"row_n = {row_n}")
        column_n = 0
        while column_n < qnt_coumns:
            # print("-"*20)
            # print(f"column_n = {column_n}")
            current_el = flat_index_list_trasposed[row_n][column_n]
            # print(f"current_el = {current_el}")
            
            if current_el == empty_value_el:
                column_n+=1
                continue
            
            if current_el not in already_seen_els:
                already_seen_els.add(current_el)
                column_n+=1
            else:            
                # print(f" came across already seen el = {current_el}")
                new_unique_el = generate_unique_el(current_el, already_seen_els, uniquelizetor=uniquelizetor)
                new_unique_el = str(new_unique_el)
                # print(f"updating element row = {row_n}, column = {column_n} with new_unique_el = {new_unique_el}")
                # flat_index_list_trasposed[row_n][column_n] = new_unique_el
                # column_n+=1
                while column_n < qnt_coumns:
                    if flat_index_list_trasposed[row_n][column_n] == current_el:
                        # print(f"updating in a loop element row = {row_n}, column = {column_n} with new_unique_el = {new_unique_el}")
                        flat_index_list_trasposed[row_n][column_n] = new_unique_el
                        column_n+=1
                        continue
                    else:
                        break
                    
                already_seen_els.add(new_unique_el)
                
            
    # print(flat_index_list_trasposed)
    
    flat_index_list_trasposed_back = list(map(list, zip(*flat_index_list_trasposed)))
    
    # print(f" flat_index_list_trasposed_back = {flat_index_list_trasposed_back}")
    
    new_index= pd.MultiIndex.from_tuples(flat_index_list_trasposed_back, names=index_names)
    
    df.set_index(new_index, inplace=True, verify_integrity=True)
    
    # print(df)
    
    return df


def prepare_sunburst_data_input(df, column_to_pick, fix_data=True):
    # column_to_pick = 2020
    
    columns=df.columns
    
    # checking whether columns is a multiindex
    check_presence_of_column_in_dataframe(df, column_to_pick)
    
    # print(df)
    
    # creating a copy of the df with only one column column_to_pick
    df = df[[column_to_pick]].copy()
    
    # print('df after "df[[column_to_pick]].copy()" ')
    
    # print(df)
    
    
    if not fix_data:
        # checking, that the column_to_pickdoes not contain any negative values
        if df[column_to_pick].min() < 0:
            raise ValueError(f"column_to_pick = {column_to_pick} contains negative values")
        
    else:
        # creating a new dataframe with only positive values
        df = df[df[column_to_pick] > 0].copy()
    
    # this is to prevent "indexing past lexsort depth" warning in Pandas
    # https://stackoverflow.com/a/54520922/4432107
    df.sort_index(inplace=True)
    
    df = uniquelize_multiindex_levels(df)
    
    # print("unuqelized df = ")
    # print(df)
    
    sunburst_data_input = []
    for level in range(0,df.index.nlevels):
        # print(f"\n********     level = {level}  ********************************************************")
        my_pivot_groupped = df.groupby(level=list(range(0,level+1))).sum()
        # print(f"my_pivot_groupped = {my_pivot_groupped}")
        
        for row_index, row_data in my_pivot_groupped.iterrows():
            # print(f"-"*20)
            # print(f"row_index = {row_index}")
            # print(f"row_data = {row_data[column_to_pick]}")
            # print(f"row_data_type = {type(row_data)}")
            sunburst_data_input_el = {}
            
            if level == 0:
                sunburst_data_input_el['name']=row_index
                sunburst_data_input_el['parent']=""
                sunburst_data_input_el['value'] = row_data[column_to_pick]
            else:
                name = row_index[-1]
                
                if name == "_":
                    
                    # print("!!!!!!!!!!!  name == '_'  !!!!!!!!!!!!!!!!!!!!  ")
                    
                    my_pivot_groupped_with_one_level_less = my_pivot_groupped.groupby(level=list(range(0,level))).sum()
                    # print(f"my_pivot_groupped_with_one_level_less = {my_pivot_groupped_with_one_level_less}")
                    
                    index_of_els_with_the_same_parent = row_index[:level]
                    
                    # print(f"index_of_els_with_the_same_parent = {index_of_els_with_the_same_parent}")
                    
                    qnt_rows_with_the_same_parent = len(df.loc[index_of_els_with_the_same_parent])
                    
                    # print(f"qnt_rows_with_the_same_parent = {qnt_rows_with_the_same_parent}")
                    
                    if qnt_rows_with_the_same_parent == 1:
                        continue
                    else:       
                        sunburst_data_input_el['name']=row_index[-2]+"_"
                        sunburst_data_input_el['parent']=row_index[-2]
                        sunburst_data_input_el['value']=row_data[column_to_pick]
                    
                else:
                    sunburst_data_input_el['name']=row_index[-1]
                    sunburst_data_input_el['parent']=row_index[-2]
                    sunburst_data_input_el['value']=row_data[column_to_pick]
                    
                
            # print(f"sunburst_data_input_row = {sunburst_data_input_el}")
            sunburst_data_input.append(sunburst_data_input_el)
            
    # print(f"sunburst_data_input = ")
    # pprint(sunburst_data_input)
    
    sunburst_figure_ready_data ={'names': [], 'parents': [], 'values': []}
    
    for el in sunburst_data_input:
        sunburst_figure_ready_data['names'].append(el['name'])
        sunburst_figure_ready_data['parents'].append(el['parent'])
        sunburst_figure_ready_data['values'].append(el['value'])
    
    return sunburst_figure_ready_data


def remove_empty_rows(df:pd.DataFrame, threshold:float = 0.0)->pd.DataFrame:
    """
    Function takes a dataframe and removes all rows, where all values in every column with dtype 'number' 
    is either NaN its aboslute value is less that a threshold parameter

    Args:
        df (pd.DataFrame): _description_

    Returns:
        pd.DataFrame: _description_
    """
    
    number_column_only_df = df.select_dtypes(include=['number'])
    
    # This will be a series with True for rows to remove and False for rows to keep
    rows_to_remove_series = ((number_column_only_df.abs()<=threshold ) | (number_column_only_df.isna())).all(axis='columns')
    
    return df[~rows_to_remove_series]
    

def main():
    data = {'indexcol':['row1','row2','row3'],
            'col1':[1.0,0.0,3.0], 
            'col2':[4.0,np.nan,6.0]}

    
    df = pd.DataFrame.from_dict(data )

    df=df.set_index(['indexcol'])

    # print(df)
    # print(df.dtypes)

    df = convert_columns_to_float(df)

    print(df)
    print(df.dtypes)

    full_rows = remove_empty_rows(df)
    
    print(full_rows)


if __name__ == "__main__":
    main()
