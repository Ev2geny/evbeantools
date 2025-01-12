"""
Set of utilities, which are used to test the function get_equiv_sing_curr_entries against beanquery results
"""
import datetime
from pprint import pformat, pprint
import io
import functools
import logging
import textwrap
from pprint import pformat
import hashlib
import pickle

import beancount
from beancount.parser import printer
from beancount.core.number import D
from beancount.core.inventory import Inventory

from beanquery import query

from evbeantools.summator import InventoryAggregator


logger = logging.getLogger()

def format_entries(entries) -> str:
    """Helper function to convert entries to string, similar  to printer.print_entries

    Args:
        entries (_type_): _description_

    Returns:
        str: _description_
    """
    entries_str = ""
    for entry in entries:
        entries_str += printer.format_entry(entry) + "\n"
    return entries_str

def beanq_2_invent_agg(entries, options, query_str) -> InventoryAggregator:
    """
    A helper function, which runs a query on entries and returns the result as an InventoryAggregator
    Only works with queries, which return 2 columns. The 1st one is an account, the second one is an inventory.
    
    Args:
        entries: list of entries
        options: dict of options
    
    Returns:
        list of inventory aggregation entries
    """
    rtypes, rows = query.run_query(entries, options, query_str, numberify=False) 
        
    assert len(rtypes) == 2, "Query must return 2 columns. The 1st one is an account, the second one is an inventory."
    assert rtypes[0].datatype == str, "First column must be account"
    assert rtypes[1].datatype == beancount.core.inventory.Inventory, "Second column must be inventory"
    
    inv_agg = InventoryAggregator()
    
    for row in rows:
        account = row[0]
        inventory = row[1]
        
        # checking that account already exists in the inventory aggregaror
        # Not sure it is even possible to have the same account in the query result more than once, but just in case
        if account in inv_agg:
            raise ValueError(f"Account {account} is returned more than once in the query result")
        
        inv_agg[account] = inventory
        
    return inv_agg


def get_net_worth_via_beanq_as_ia(entries, options, currency, date: datetime.date, account_depth: int = 1000) -> InventoryAggregator:
    """
    Uses a beanquery engin to calculate a net worth (with details per account) at a certain date with an attempt to 
    express this in single currency. 
    
    Following the standard accounting practices, when converting to a single currency, 
    the exchange rate is taken at the date for which the net worth is calculated.
    
    Following the standard functionality of beanquery, if result cannot be converted to a single currency, then the 
    values in unconvertable currencies are returned as is.
    
    Result is returned as a set of Accounts to Inventory pairs, stored in an InventoryAggregator
    """
    
    date_iso: str = date.isoformat()
    
    name_assets = options["name_assets"]
    name_liabilities = options["name_liabilities"]
    
    query = f"""
    SELECT root(account, {account_depth}) as account, convert(SUM(position),'{currency}',{date_iso}) as amount
    where date <= {date_iso} AND account ~ '{name_assets}|{name_liabilities}'
    """
    res = beanq_2_invent_agg(entries, options, query)
    
    return res


def get_statement_of_change_in_net_worth_beanq_as_ia(entries, options, currency, start_date: datetime.date, 
                                                     end_date: datetime.date, account_depth:int = 1000) -> InventoryAggregator:
    
    """
    Uses a beanquery engin to calculate a statement of change in net worth over a period of time and attempts to 
    convert the result to a single currency. 

    Changes to net worth are defined as the ones, coming from postings to income, expenses or equity accounts over the 
    specified period. 
    
    Result is returned not as a single value, but is broken as a set of an account to value pairs,  stored in an 
    InventoryAggregator, where the accounts, belong to income, expenses or equity.
    
    Following the standard accounting practices, when converting to a single currency, 
    the exchange rate is taken at the date of each individual transaction.
    
    Following the standard functionality of beanquery, if result cannot be converted to a single currency, then the 
    values in unconvertable currencies are returned as is.
    
    The function is used for testing against beanquery
    
    """
    
    start_date_iso = start_date.isoformat()
    end_date_iso = end_date.isoformat()
    
    name_expenses = options["name_expenses"]
    name_income = options["name_income"]
    name_equity = options["name_equity"]
    
    # Converting with the date being the date of the transaction
    query = f"""
    SELECT root(account, {account_depth}) as account, SUM(convert(position, '{currency}', date)) as amount
    WHERE account ~ '{name_expenses}|{name_income}|{name_equity}' AND
    date >= {start_date_iso} AND
    date <= {end_date_iso} 
    """
    res = beanq_2_invent_agg(entries, options, query)
    
    return res
    
class EntriesUnchangedChecker:
    """
    This class tests that entries have not changed 
    The function load_original_entries loads the original entries, and serializes them into the pickle format
    
    When the function confirm_entries_unchanged is called, it compares the original entries with the new ones
    To do this comparison, it reverts the original entries and then compares them entry by entry with the new entries
    When comparing individual entries, it once again serializes them both entries to pickle format and then compares 
    the hashes of the serialized objects
    """
    
    def __init__(self):
        self.serialized_original_entries = None
    
    def load_original_entries(self, entries):
        self.serialized_original_entries = pickle.dumps(entries)
        
    def _get_hash(self, obj):
        """
        Create a checksum of all the data in the object.
        
        Args:
            obj: The object to create a checksum for.
            
        Returns:
            str: The checksum of the object.
        """
        # Serialize the object to a byte stream
        serialized_obj = pickle.dumps(obj)
        
        # Create a hash of the serialized object
        checksum = hashlib.sha256(serialized_obj).hexdigest()
        
        return checksum
        
    def _compare_entries(self, entry_orig, entry2, entry_num):
        """
        Compares two entries. If they are different, returns the string, explaining the difference.
        If they are the same, returns None
        
        The entries are compared by serializing them and comparing the hashes of the serialized objects
        
        params:
            entry_orig: the original entry
            entry2: the new entry
            entry_num: the number of the entry in the list of entries (used in the error message)
        
        """
        entry1_hash = self._get_hash(entry_orig)
        entry2_hash = self._get_hash(entry2)
        
        error_msg = ""
        
        if entry1_hash != entry2_hash:
            error_msg += f"\n** Original entry {entry_num}********************************:\n {format_entries([entry_orig])}\n"
            error_msg += f"\n** New entry***:\n {format_entries([entry2])}\n"
            
        if len(error_msg) > 0:
            return error_msg
        else:
            return None
        
    def confirm_entries_unchanged(self, entries):
        
        recovered_original_entries = pickle.loads(self.serialized_original_entries)
        
        # TODO: add more details to the error message
        if len(recovered_original_entries) != len(entries):
            raise RuntimeError("The number of entries has changed")
        
        comp_results = ""
        
        for i, (entry1, entry2) in enumerate(zip(recovered_original_entries, entries)):
            comp_result = self._compare_entries(entry1, entry2, i)
            if comp_result:
                comp_results += comp_result
        
        if len(comp_results) > 0:
            raise RuntimeError(f"Original entries have changed. The differences are: {comp_results}")
    
    
def check_vs_beanquery(get_equiv_sing_curr_entries_func):
    """
    A decorator function, which verifies the get_equiv_sing_curr_entries function against beanquery results
    It may make sense to use this decorator even in case of a production code, because it will help to catch inconsistencies
    
    It performs the following tests:
        TEST1 Checking that beancount has processed new entries without errors
        TEST2 Checking that the net worth (verified per account) at the start date is the same when calculated on the original entries. 
        TEST3 Checking that the net worth at the end date is the same when calculated on the original entries and on the converted entries
        TEST4 Checking that the statement of change report (which is the same as P&L, if there are no equity transactions), 
              converted entries is equal to the net worth difference
        TEST5 Checking that the statement of net worth change report,  when calculated on on converted entries and the statement of 
          net worth change report over the same period when calculated on the original entries  is only present in 2 accounts:  
            - unreal_gains_p_l_acc and its children
            - account_for_price_diff (in the current implementation it is the same as unreal_gains_p_l_acc)
        TEST6 Checking that the original entries have not changed
    
    """
    
    # This is a tolerance, which is used as a virtual zero, when comparing values, which theoretically should be zero, 
    # but due to the floating point arithmetic are not
    
    # tolerance = D("0.001")
    
    @functools.wraps(get_equiv_sing_curr_entries_func)
    def wrapper(*args, **kwargs):
        
        logger.debug(f"wrapper is called with the following arguments ")
        logger.debug(f"Positional arguments:\n {pformat(args)}")
        logger.debug(f"key word arguments:\n {pformat(kwargs)}")
        
        entries_unchanged_checker = EntriesUnchangedChecker()
        entries_unchanged_checker.load_original_entries(args[0])
        
        # Getting the result of the function
        result = get_equiv_sing_curr_entries_func(*args, **kwargs)
        
        # Capturing positional only arguments, given to the function, being decorated
        entries, options = args[0], args[1]
        
        target_currency = None
        if len(args) >= 3:
            target_currency = args[2]
        else:
            if target_currency := kwargs.get("target_currency", None):
                pass
            else:      
                if len(options["operating_currency"]) > 0:
                    target_currency = options["operating_currency"][0]
                else:
                    raise RuntimeError("Target currency is not provided in positional arguments, nor in key word arguments, nor in options")
        
        # capturing arguments, which can be both positional and keyword only, given to the function, being decorated
        start_date = None
        if len(args) >= 4:
            start_date = args[3]
        else:
            start_date = kwargs.get("start_date")
            
        if isinstance(start_date, str):
            start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            
        if not start_date:
                start_date = entries[0].date
        
        
        end_date = None    
        if len(args) >= 5:
            end_date = args[4]
        else:
            end_date = kwargs.get("end_date", None)
            
        if isinstance(end_date, str):
            end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
            
        if not end_date:
                end_date = entries[-1].date            
            
        # Importing the accounts, which are expected to have the difference in the P&L over the period
        # Doing this here to avoid circular imports problem. 
        # Re https://rollbar.com/blog/how-to-fix-circular-import-in-python/
        from .sing_curr_conv import UNREAL_GAINES_P_AND_L_ACC, ACC_FOR_PRICE_DIFF, TOLERANCE_DEF
        # UNREAL_GAINES_P_AND_L_ACC = sing_curr_conv.UNREAL_GAINES_P_AND_L_ACC
        # ACC_FOR_PRICE_DIFF = sing_curr_conv.ACC_FOR_PRICE_DIFF
        
        # capturing keyword only arguments, given to the function, being decorated
        # Note: unreal_gains_p_l_acc are actually the same account. They are left in the code as different one for historical reasons
        # TODO: Consider merging them into one in the code as well
        unreal_gains_p_l_acc = kwargs.get("unreal_gains_p_l_acc", UNREAL_GAINES_P_AND_L_ACC)
        account_for_price_diff = kwargs.get("account_for_price_diff", ACC_FOR_PRICE_DIFF)
        self_testng_mode = kwargs.get("self_testing_mode", False)
        tolerance = D(kwargs.get("tolerance", TOLERANCE_DEF))
        
        logger.debug(f"tolerance_wrapper: {tolerance}") 
            
        # These are entries, errors and options, when converted to single currency
        entries_eqv, errors_eqv, options_eqv = result
        
        if not self_testng_mode:
            logger.debug(f"Skipping the self testing mode.")
            return result
        
        logger.debug(f"Checking the function {get_equiv_sing_curr_entries_func.__name__} against beanquery")
        
        # **** TEST1 Checking that beancount has processed new entries without errors *****
        if len(errors_eqv) > 0:
            
            file_replacement_io = io.StringIO()
            printer.print_errors(errors_eqv, file=file_replacement_io)
            errors_str = file_replacement_io.getvalue()
            
            error_msg = f"""
                beancount has found qnt {len(errors_eqv)} errors in the converted entries after
                converting them by the function {get_equiv_sing_curr_entries_func.__name__}. Errors:\n{errors_str}.
                """
            error_msg = textwrap.dedent(error_msg)
            raise RuntimeError(error_msg)
        
        # **** TEST2 Checking that the net worth at the start date is the same when calculated on the original entries 
        # and on the converted entries ****
        
        date_before_start_date = start_date - datetime.timedelta(days=1)
        
        net_worth_start = get_net_worth_via_beanq_as_ia(entries,
                                                        options,
                                                        target_currency, 
                                                        date_before_start_date).clean_empty()
        
        logger.debug(f"net_worth_start:\n {pformat(net_worth_start)}")
        
        net_worth_start_eqv = get_net_worth_via_beanq_as_ia(entries_eqv, 
                                                            options_eqv,
                                                            target_currency,
                                                            date_before_start_date).clean_empty()
        
        logger.debug(f"net_worth_start_eqv:\n {pformat(net_worth_start_eqv)}")
        
        net_worth_start_diff = (net_worth_start_eqv - net_worth_start).clean_empty()
        
        
        if not net_worth_start_diff.is_small(tolerance):
            raise RuntimeError(f"Net worth at the date before the start date {date_before_start_date} is different \
            when calculated on the on the original entries and on the converted entries. \n \
            Calculated on original entries:\n {pformat(net_worth_start)} \n Calculated on converted entries:\n {pformat(net_worth_start_eqv)} \n \
            The difference is {net_worth_start_diff}")
        
        
        # **** TEST3 Checking that the net worth at the end date is the same when calculated on the original entries 
        # and on the converted entries ****
        
        net_worth_end = get_net_worth_via_beanq_as_ia(entries, options,
                                                                target_currency, 
                                                                end_date).clean_empty()
        
        logger.debug(f"net_worth_end:\n {pformat(net_worth_end)}")
        
        net_worth_end_eqv = get_net_worth_via_beanq_as_ia(entries_eqv,
                                                          options_eqv,
                                                          target_currency,
                                                          end_date).clean_empty()
        
        logger.debug(f"net_worth_end_eqv:\n {pformat(net_worth_end_eqv)}")
        
        net_worth_end_diff = (net_worth_end_eqv - net_worth_end).clean_empty()
        
        if not (net_worth_end - net_worth_end_eqv).is_small(tolerance):
            
            error_msg = f"""
                Net worth at the end date {end_date} is different 
                when calculated on the on the original entries and on the converted entries. 
                Calculated on original entries:
                {pformat(net_worth_end)}
                
                Calculated on converted entries: 
                {pformat(net_worth_end_eqv)}
                The difference is
                {pformat(net_worth_end_diff)}
                """
            error_msg = textwrap.dedent(error_msg)
            
            raise RuntimeError(error_msg)
            
            
        # **** TEST4 Checking that the P&L (or rather statement of change, because it also includes Equity) over the period 
        # on converted entries is equal to the net worth difference **** 
           
        statement_of_change_via_beanq_eqv_ent_ia: InventoryAggregator = get_statement_of_change_in_net_worth_beanq_as_ia(entries_eqv, 
                                                                                    options_eqv, 
                                                                                    target_currency, 
                                                                                    start_date, 
                                                                                    end_date).clean_empty()
        
        logger.debug(f"pa_and_l_via_beanq_eqv_ent_ia:\n {pformat(statement_of_change_via_beanq_eqv_ent_ia)}")
        
        p_and_l_calc_via_beanq_eqv_ent_inv: Inventory = statement_of_change_via_beanq_eqv_ent_ia.sum_all()
        
        logger.debug(f"p_and_l_calc_via_beanq_eqv_ent_inv:\n {pformat(p_and_l_calc_via_beanq_eqv_ent_inv)}")
        
        
        # We need to negate the result, because beancount is using a signed double entries accounting, where the P&L is a negative number, if the net worth has increased
        net_worth_change_diff_inv: Inventory = -(net_worth_end - net_worth_start).sum_all()
        
        diff_in_net_worth_diff_inv: Inventory = -p_and_l_calc_via_beanq_eqv_ent_inv + net_worth_change_diff_inv
                
        if not diff_in_net_worth_diff_inv.is_small(tolerance):
            raise RuntimeError(f"Net worth change calculated via P&L query on the converted entries is different from the difference in net worth, calculated on the original entries. \n \
            Calculated on converted entries: {pformat(p_and_l_calc_via_beanq_eqv_ent_inv)} \n \
            The difference in net worth is {pformat(net_worth_change_diff_inv)} \n \
            The difference between the two is {pformat(diff_in_net_worth_diff_inv)}")
            
            
        # **** TEST5 Checking that the statement of net worth change report,  when calculated on on converted entries and the statement of 
        # net worth change report over the same period when calculated on the original entries  is only present in 2 accounts:  
        #   - unreal_gains_p_l_acc and its children
        #   - account_for_price_diff (in the current implementation it is the same as unreal_gains_p_l_acc)
        p_and_l_via_beanq_ia: InventoryAggregator = get_statement_of_change_in_net_worth_beanq_as_ia(entries, 
                                                                            options, 
                                                                            target_currency, 
                                                                            start_date, 
                                                                            end_date).clean_empty()
        
        p_and_l_diff: InventoryAggregator = (p_and_l_via_beanq_ia - statement_of_change_via_beanq_eqv_ent_ia).clean_small(tolerance)
        
        # p_and_l_diff_accounts will contain accounts, which contain inventories, which are different in P&L calculated on the original entries
        # and P&L calculated on the converted to single currency entries
        # These should either be children of the unreal_gains_p_l_acc or an account_for_price_diff
        p_and_l_diff_accounts: list = p_and_l_diff.keys()
        
        unexpected_acc_in_difference = []
        for account in list(p_and_l_diff_accounts):
            if not (account == account_for_price_diff or unreal_gains_p_l_acc in account):
                unexpected_acc_in_difference.append(account)
        
        if len(unexpected_acc_in_difference) > 0:
            raise RuntimeError(f"Accounts, which are different in the P&L over the period when calculated on the original entries and on the converted entries, \
            are not the same as expected. The difference is {pformat(p_and_l_diff_accounts_set)}")
              
              
        # ****** TEST 6 Checking that the original entries have not changed ********
        entries_unchanged_checker.confirm_entries_unchanged(args[0])
              
        return result

    return wrapper