"""
Tools for building Plotly sunburst diagrams from pandas dataframes.
The main function is :func:`get_sunburst_figure_from_pivot`, which takes a dataframe with a multiindex and a column 
name, and produces a Plotly figure with a sunburst diagram representing the hierarchical data in the dataframe.
"""


from typing import Any, Dict, List, Tuple, Union
from collections import defaultdict

import pandas as pd

import plotly.graph_objects as go



# This is an old version

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
    # check_presence_of_column_in_dataframe(df, column_to_pick)
    
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
    for level in range(0, df.index.nlevels):
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