import unittest
import pytest
import datetime
import logging
import re
import io
from pprint import pprint, pformat
from pathlib import Path
import textwrap
import tempfile
import os

import beancount
from beancount import loader
from beancount.parser import printer
from beancount.core.data import Account, Transaction
from beancount.core import inventory
from beancount.core.inventory import Inventory
from beancount.core.prices import build_price_map
from beancount.loader import load_string, load_file

from beanquery import query

from evbeantools.sing_curr_conv import get_equiv_sing_curr_entries, build_currency_introduction_map, get_fist_date_of_price, print_entries_to_string, print_errors_to_string
from evbeantools.sing_curr_conv import parse_conf_string, UNREAL_GAINES_P_AND_L_ACC, GAINS_SUFFIX
from evbeantools.sing_curr_conv import UnconvertableCommBecomesConvertibleErr, TransferFundsToFromUnconvertableCommErr
from evbeantools.summator import InventoryAggregator
from evbeantools.sing_curr_conv_utils import get_net_worth_via_beanq_as_ia, get_statement_of_change_in_net_worth_beanq_as_ia
from evbeantools.sing_curr_conv_utils import beanq_2_invent_agg, format_entries

# wexpect is only for windows
if os.name == 'nt':
    import wexpect
# else:
#     import pexpect

I = inventory.from_string

logger = logging.getLogger()

UNREAL_GAINES_ACC_ROOT = UNREAL_GAINES_P_AND_L_ACC


def get_accounts_which_start_with(entries, account_starting_pattern: str) -> set[Account]:
    """Function returns a set of all accounts in the leger, which start with the specific string pattern

    Args:
        entries (_type_): _description_
        account_starting_pattern (_type_): 

    Returns:
        bool: True if the unrealized gains accounts are present in the entries, False otherwise
    """
    # Getting the string representation of the entries
    
    result = set()
    
    for entry in entries:
        if not isinstance(entry, Transaction):
            continue
        
        for posting in entry.postings:
            if posting.account.startswith(account_starting_pattern):
                result.add(posting.account)
            
    return result

class MiscTests(unittest.TestCase):
    @loader.load_doc()
    def test_build_price_introduction_map(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Income:Salary
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
    
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking     1000 USD
            Equity:Opening-Balances -1000 USD
            
        
        2020-01-02 * "Buying something USD"
            Assets:Bank:Checking     -100 USD
            Expenses:Misc            100 USD
       
        2020-01-03 * "Salary EUR"
            Income:Salary            -1000 EUR
            Assets:Bank:Checking      1000 EUR
        """
        
        price_introduction_map = build_currency_introduction_map(entries)
        
        expected_map = {'EUR': datetime.date(2020, 1, 3), 'USD': datetime.date(2020, 1, 1)}
        
        self.assertEqual(price_introduction_map, expected_map)
        
    @loader.load_doc()
    def test_get_fist_date_of_price(self, entries, errors, options):
        """
        2020-01-01 price EUR 2 USD
        2020-01-02 price EUR 3 USD
        """
        
        price_map = build_price_map(entries)
        
        first_date_EUR_USD = get_fist_date_of_price(price_map, ("EUR", "USD"))
        
        print(first_date_EUR_USD)
        
        self.assertEqual(first_date_EUR_USD, datetime.date(2020, 1, 1))
        
        fist_date_EUR_GBP = get_fist_date_of_price(price_map, ("EUR", "GBP"))
        
        print(fist_date_EUR_GBP)
        
        self.assertIsNone(fist_date_EUR_GBP)
        
    def test_parse_conf_string(self):
        str = "'post_par1', 2, kwpar=1, kwpar2='b'"
        # str = "kwpar=1, kwpar2='b'"
        
        args, kwargs = parse_conf_string(str)
        
        self.assertEqual(args, ['post_par1', 2])
        self.assertEqual(kwargs, {'kwpar': 1, 'kwpar2': 'b'})

def verify_unrealized_gains(entries,
                            options,
                            expected_result: list[tuple[Account, str, str, str, Inventory]], 
                            unreal_gain_acc_root: str = UNREAL_GAINES_P_AND_L_ACC,
                            group_p_l_acc_tr = False):
    """
    A helper function to verify the unrealized gains in the entries are as expected by using the beanquery engine
    
    params:
        entries: list of entries
        
        options: options
        
        expected_result: list of tuples, where each tuple is a tuple of the following:
            - Account: the account of the unrealized gains
            - str: the value of the 'scc_at_cost' meta field, which can be 'at_cost' or 'no_cost'
            - str: the value of the 'scc_unreal_g_cause', which can be 'price_change' or 'price_diff
            - str: the value of the 'scc_bal_s_acc' meta field
            - Inventory: the expected amount of the unrealized gains
            
        unreal_gain_acc_root: the root of the unrealized gains accounts
        group_p_l_acc_tr: should be set to the same value as the 'group_p_l_acc_tr' option, when calling the 
                          get_equiv_sing_curr_entries function, which created these single currency entries     
        
    
    """
    
    unrealyzed_gains_dive_in_q = f"""
        SELECT account, meta['scc_at_cost'], meta['scc_unreal_g_cause'], meta['scc_bal_s_acc'] as scc_bal_s_acc, SUM(position) as amount
        WHERE account ~ '^{unreal_gain_acc_root}'
        GROUP BY account, meta['scc_at_cost'], meta['scc_unreal_g_cause'], meta['scc_bal_s_acc']
        """
               
    unrealyzed_gains_q_res = query.run_query(entries, options, unrealyzed_gains_dive_in_q)
    
    unrealyzed_gains_q_res_rows = sorted(unrealyzed_gains_q_res[1])
    
    expected_result_rows = sorted(expected_result)
        
    if not unrealyzed_gains_q_res_rows == expected_result_rows:
        
        error_msg = f"""
                     \n
                     Unrealyzed gains result is not as expected
                     Expected: 
                     {expected_result_rows}
                     Calculated: 
                     {unrealyzed_gains_q_res_rows}
                    """
        error_msg = textwrap.dedent(error_msg).strip()
        
        raise AssertionError(error_msg)
    
def verify_different_objects(entries_orig: list, entries_conv: list):
    """
    A helper function to verify, that entries1 and entries2 are all different objects.
    If any of the entries in entries1 is the same object as any of the entries in entries2, the function will raise an
    AssertionError
    """
    orig_ids = {id(entry) for entry in entries_orig}
    conv_ids = {id(entry) for entry in entries_conv}
    
    intersection_ids = orig_ids.intersection(conv_ids)
    
    if intersection_ids:
        errors_string = ""
        qnt_errors_found = 0
        
        for entry_orig in entries_orig:
            if id(entry_orig) in intersection_ids:
                qnt_errors_found += 1
                errors_string += f"\n*** The same object Error {qnt_errors_found} *********\n"
                errors_string += format_entries([entry_orig])
        
        raise AssertionError(f"The following objects are found to be the same\n {errors_string}")

    
class TestSingCurrConv(unittest.TestCase):
    
    @loader.load_doc()
    def test_simple_case_no_transaction(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking      100 USD
            Equity:Opening-Balances  -100 USD
            
        2020-01-03 price EUR 2 USD
        """
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2020, 1, 2),
                                                                                      datetime.date(2020, 1, 3),
                                                                                      self_testing_mode=True)  
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:EUR-USD", 
                                  "no_cost", 
                                  "price_change", 
                                  "Assets:Bank:Checking", 
                                  I("50 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
        
    @loader.load_doc()
    def test_simple_case_no_transaction_mult_acc(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2 
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1      100 USD
            Assets:Bank:Checking2      200 USD
            Equity:Opening-Balances   -300 USD
            
        2020-01-03 price EUR 2 USD
        """
        
        with self.subTest("Test with group_p_l_acc_tr=False"):
        
            entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                        self_testing_mode=True)  
            
            printer.print_entries(entries_eqv)
            
            verify_different_objects(entries, entries_eqv)
            
            expected_unreal_gains = [("Income:Unrealized-Gains:EUR-USD", 
                                    "no_cost", 
                                    "price_change", 
                                    "Assets:Bank:Checking1", I("50 EUR")),
                                    ("Income:Unrealized-Gains:EUR-USD", 
                                    "no_cost", 
                                    "price_change", 
                                    "Assets:Bank:Checking2", I("100 EUR"))]
            
            verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
            
            
        with self.subTest("Test with group_p_l_acc_tr=True"):
        
            entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                        self_testing_mode=True,
                                                                                        group_p_l_acc_tr=True)  
            
            printer.print_entries(entries_eqv)
            
            verify_different_objects(entries, entries_eqv)
            
            expected_unreal_gains = [("Income:Unrealized-Gains:EUR-USD", 
                                    "no_cost", 
                                    "price_change", 
                                    None, 
                                    I("150 EUR"))]
            
            verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    @loader.load_doc()
    def test_simple_case_with_transaction(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking   -100 USD
            Expenses:Misc           100 USD
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2020, 1, 2),
                                                                                      datetime.date(2020, 1, 3),
                                                                                      self_testing_mode=True) 
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:EUR-USD", 
                                  "no_cost", 
                                  "price_change", 
                                  'Assets:Bank:Checking', 
                                  I("450 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    @loader.load_doc()
    def test_simple_case_with_transaction_mul_curr(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Assets:Bank:Checking  1000 EUR
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking  
            Expenses:Misc         100 USD
            
        2020-01-02 * "Buying something EUR"
            Assets:Bank:Checking   -100 EUR 
            Expenses:Misc           100 EUR
            
            
        2020-01-03 price EUR 2 USD
        """
     
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2020, 1, 2),
                                                                                      datetime.date(2020, 1, 3),
                                                                                      self_testing_mode=True) 
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:EUR-USD", 
                                  "no_cost", 
                                  "price_change",
                                  'Assets:Bank:Checking', 
                                  I("450 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    # Testing the case, when the price changes on the same date as the transaction
    @loader.load_doc()
    def test_simple_case_with_transaction_mul_curr_price_change_the_same_date(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Assets:Bank:Checking  1000 EUR
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking  
            Expenses:Misc          100 USD
            
        2020-01-02 * "Buying something EUR"
            Assets:Bank:Checking  
            Expenses:Misc          100 EUR
            
            
        2020-01-02 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2020, 1, 2),
                                                                                      datetime.date(2020, 1, 3),
                                                                                      self_testing_mode=True) 
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 'price_change', 
                                  'Assets:Bank:Checking', 
                                  I("500.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    @loader.load_doc()
    def test_simple_case_with_transaction_and_equity(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Equity:Drawings
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking     -100 USD
            Expenses:Misc            100 USD
            
        2020-01-03 * "Equity withdrawal"
            Assets:Bank:Checking -500 USD  
            Equity:Drawings
            
        2020-01-04 price EUR 2 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2020, 1, 2),
                                                                                      datetime.date(2020, 1, 5),
                                                                                      self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking', 
                                  I("200.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    # Testing the case, when the provided start date is earlier than the first transaction date
    @loader.load_doc()
    def test_simple_case_with_transaction_early_start_date(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking   -100 USD
            Expenses:Misc           100 USD
            
        2020-01-03 price EUR 2 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2019, 1, 1),
                                                                                      datetime.date(2020, 1, 3),
                                                                                      self_testing_mode=True) 
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:EUR-USD", 
                                  "no_cost", "price_change", 
                                  'Assets:Bank:Checking',
                                  I("450 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
    # Testing the case, when the start date is later than the finish date
    @loader.load_doc()
    def test_simple_case_with_transaction_start_after_finish(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking   -100 USD
            Expenses:Misc           100 USD
            
        2020-01-03 price EUR 2 USD
        """
        # printer.print_entries(entries)
    
        with self.assertRaises(ValueError):
            entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                        datetime.date(2020, 1, 4),
                                                                                        datetime.date(2020, 1, 2),
                                                                                        self_testing_mode=True) 
  
    # Testing the case, when the provided start and finish dates not provided
    @loader.load_doc()
    def test_simple_case_start_finish_dates_not_provided(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking   -100 USD
            Expenses:Misc           100 USD
            
        2020-01-03 price EUR 2 USD
        """

        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                    None,
                                                                                    None,
                                                                                    self_testing_mode=True) 
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:EUR-USD", 
                                  "no_cost", "price_change",
                                  'Assets:Bank:Checking',
                                  I("450 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    @loader.load_doc()
    def test_simple_case_with_cost(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 100 USD
            
        2020-01-04 * "Buying at cost"
            Assets:Bank:Checking  
            Assets:Investments     2 IVV {100 USD} @ 100 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           datetime.date(2020, 1, 2),
                                                                           datetime.date(2020, 1, 5),
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = []
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    @loader.load_doc()
    def test_simple_case_with_cost_and_with_price_change(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 100 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  
            Assets:Investments 2 IVV {100 USD}
            
        2020-01-04 price IVV 200 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           datetime.date(2020, 1, 2),
                                                                           datetime.date(2020, 1, 5),
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:USD-IVV", 
                                  "at_cost", 
                                  "price_change",
                                  'Assets:Investments',
                                  I("-200 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    @loader.load_doc()
    def test_with_cost_and_two_commodities_on_the_same_acc(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 100 USD
        2020-01-02 price HOO 150 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  
            Assets:Investments 2 IVV {100 USD}
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  
            Assets:Investments 2 HOO {150 USD}
            
        2020-01-04 price IVV 200 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           datetime.date(2020, 1, 2),
                                                                           datetime.date(2020, 1, 5),
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:USD-IVV", 
                                  "at_cost", 
                                  "price_change",
                                  'Assets:Investments',
                                  I("-200 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    @loader.load_doc()
    def test_with_cost_and_two_positions_the_same_acc(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 100 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  
            Assets:Investments 2 IVV {100 USD}
            
        2020-01-04 * "Buying at cost"
            Assets:Bank:Checking  
            Assets:Investments 2 IVV {100 USD}
            
        2020-01-05 price IVV 200 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:USD-IVV", 
                                  "at_cost", 
                                  "price_change",
                                  'Assets:Investments', 
                                  I("-400 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    # Testing the case, which will probably never happen in practice, but still seems to be possible in theory
    # Namely, when the same commodity is bought for the same account one time at cost and another time without cost
    @loader.load_doc()
    def test_with_cost_and_no_cost_the_same_acc_the_same_commodity(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 100 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking   -200 USD
            Assets:Investments     2 IVV {100 USD}
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  -400 USD
            Assets:Investments    4 IVV @ 100 USD
            
        2020-01-04 price IVV 200 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains =  [('Income:Unrealized-Gains:USD-IVV', 
                                   'at_cost', 
                                   'price_change', 
                                   'Assets:Investments',
                                   I("-200 USD")),
                                  ('Income:Unrealized-Gains:USD-IVV', 
                                   'no_cost', 
                                   'price_change', 
                                   'Assets:Investments',
                                   I("-400 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
  
    @loader.load_doc()
    def test_simple_case_with_price_and_price_change(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 100 USD
            
        2020-01-03 * "Buying IVV"
            Assets:Bank:Checking  
            Assets:Investments 2 IVV @ 100 USD
            
        2020-01-04 price IVV 200 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           datetime.date(2020, 1, 2),
                                                                           datetime.date(2020, 1, 5),
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains = [("Income:Unrealized-Gains:USD-IVV", 
                                  "no_cost", 
                                  "price_change",
                                  'Assets:Investments', 
                                  I("-200 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    # Testing the situation when unrealized gains for the same commodity are caused by 2 slightly different reasons
    #   - price change of the already purchased commodity
    #   - difference between the price of the commodity in the price entry and the price of the commodity, at which it 
    #     was bought
    @loader.load_doc()
    def test_simple_case_with_price_and_price_change_wrong_price_v2(self, entries, errors, options):
        """
        2024-01-01 open Assets:US:Bank
        2024-01-01 open Assets:EU:Bank
        2024-01-01 open Equity:Opening-Balances

        2024-01-01 price EUR 1.0 USD 

        2024-01-01 * "Openning balance "
            Assets:US:Bank      1000 USD
            Assets:EU:Bank      1000 EUR
            Equity:Opening-Balances

        2024-01-02 price EUR 2 USD 

        2024-01-03 * "Exchange USD to EUR not the ECB rate"
            Assets:EU:Bank  250 EUR @ 4 USD
            Assets:US:Bank -1000 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                           None,
                                                                           None,
                                                                           self_testing_mode=True)
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        expected_unreal_gains =  [('Income:Unrealized-Gains:EUR-USD', 
                                   'no_cost', 
                                   'price_change',
                                   'Assets:US:Bank', 
                                   I("500.0 EUR")),
                                  ('Income:Unrealized-Gains:EUR-USD', 
                                   'no_cost', 
                                   'price_diff', 
                                   'Assets:EU:Bank',
                                   I("250.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
    # The same as test_simple_case_with_price_and_price_change_wrong_price_v2, but we convert to different currency
    @loader.load_doc()
    def test_simple_case_with_price_and_price_change_wrong_price_v3(self, entries, errors, options):
        """
        plugin "beancount.plugins.auto_accounts"

        2024-01-01 price EUR 1.0 USD 

        2024-01-01 * "Openning balance "
            Assets:US:Bank      1000 USD
            Assets:EU:Bank      1000 EUR
            Equity:Opening-Balances

        2024-01-02 price EUR 2 USD 

        2024-01-03 * "Exchange USD to EUR not the ECB rate"
            Assets:EU:Bank  250 EUR @ 4 USD
            Assets:US:Bank -1000 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           None,
                                                                           None,
                                                                           self_testing_mode=True)
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
                
        expected_unreal_gains =  [('Income:Unrealized-Gains:USD-EUR', 
                                   'no_cost', 
                                   'price_change',
                                   'Assets:EU:Bank', 
                                   I("-1000.0 USD")),
                                  ('Income:Unrealized-Gains:USD-EUR', 
                                   'no_cost', 
                                   'price_diff', 
                                   'Assets:EU:Bank',
                                   I("500 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
  
    @loader.load_doc()
    def test_simple_case_with_cost_price_change_wrong_cost(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 100 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  
            Assets:Investments 2 IVV {150 USD} ; This is a cost, different from the price in the price entry
            
        2020-01-04 price IVV 200 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           datetime.date(2020, 1, 2),
                                                                           datetime.date(2020, 1, 5),
                                                                           self_testing_mode=True)
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
                
        expected_unreal_gains =  [('Income:Unrealized-Gains:USD-IVV', 
                                   'at_cost', 
                                   'price_change',
                                   'Assets:Investments', 
                                   I("-200 USD")),
                                  ('Income:Unrealized-Gains:USD-IVV', 
                                   'at_cost', 
                                   'price_diff', 
                                   'Assets:Investments',
                                   I("100 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
  
    @loader.load_doc()
    def test_simple_case_with_cost_and_gain(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Investment
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking       1000 USD
            Equity:Opening-Balances   -1000 USD
            
        2020-01-02 price IVV 150 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  -300 USD
            Assets:Investments     2 IVV {150 USD} 
            
        2020-01-04 price IVV 200 USD
        
        2020-01-05 * "Selling at a new price"
            Assets:Bank:Checking   400 USD 
            Assets:Investments     -2 IVV {150 USD} @ 200 USD
            Income:Investment      -100 USD
        """
        
        # This is where we are expecting unrealized gains to be booked
        expected_unreal_gains_acc_changing_part = "USD-IVV"
        expected_unreal_gains_acc = f"{UNREAL_GAINES_ACC_ROOT}:{expected_unreal_gains_acc_changing_part}{GAINS_SUFFIX}"
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           None,
                                                                           None,
                                                                           unreal_gains_p_l_acc=UNREAL_GAINES_ACC_ROOT,
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        net_worth_changes_before_realiz = get_statement_of_change_in_net_worth_beanq_as_ia(entries_eqv,
                                                                        options_eqv,
                                                                        "USD",
                                                                        datetime.date(2020, 1, 2),
                                                                        datetime.date(2020, 1, 4))
        
        # On 4th of January the unrealized gains are -100 USD
        self.assertEqual(net_worth_changes_before_realiz[expected_unreal_gains_acc], I("-100 USD"))        

        net_worth_changes_after_realiz = get_statement_of_change_in_net_worth_beanq_as_ia(entries_eqv,
                                                                             options_eqv,
                                                                             "USD",
                                                                             datetime.date(2020, 1, 2),
                                                                             datetime.date(2020, 1, 5))
        
        
        
        # Checking that on 5 January the unrealized gains account is present in the net worth changes, but it is empty
        # The reason it is empty is that the unrealized gains were booked back when they were realized
        
        assert expected_unreal_gains_acc in net_worth_changes_after_realiz
        assert net_worth_changes_after_realiz[expected_unreal_gains_acc].is_empty()
         
                
        expected_unreal_gains =  [('Income:Unrealized-Gains:USD-IVV', 
                                   'at_cost', 
                                   'price_change',
                                   'Assets:Investments', 
                                   I("-100 USD")),
                                  ('Income:Unrealized-Gains:USD-IVV', 
                                   'at_cost', 
                                   'price_diff', 
                                   'Assets:Investments',
                                   I("100 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
    
    # The same as test_simple_case_with_cost_and_gain, but the price at which IVV is bought and sold is different
    # from the one, which is specified in the price entry
    @loader.load_doc()
    def test_simple_case_with_cost_and_gain_wrong_price(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Investment
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 150 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  -250 USD
            Assets:Investments     2 IVV {125 USD} ; the price at which this is bought is lower, than the price in the price entry
                                                ; This price benifit is booked as unrealized gains 
            
        2020-01-04 price IVV 200 USD
        
        2020-01-05 * "Selling at a new price"
            Assets:Bank:Checking   300 USD 
            Assets:Investments     -2 IVV {125 USD} @ 150 USD ; the price at which this is sold is different from the price in the price entry
            Income:Investment      -50 USD
        """
        
        # # This is where we are expecting unrealized gains to be booked
        # expected_unreal_gains_acc = "Income:Unrealized-Gains:USD-IVV-changes"
        
        expected_unreal_gains_acc_changing_part = "USD-IVV"
        expected_unreal_gains_acc = f"{UNREAL_GAINES_ACC_ROOT}:{expected_unreal_gains_acc_changing_part}{GAINS_SUFFIX}"
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           None,
                                                                           None,
                                                                           unreal_gains_p_l_acc="Income:Unrealized-Gains",
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv)
        
        net_worth_changes_before_realiz = get_statement_of_change_in_net_worth_beanq_as_ia(entries_eqv,
                                                                        options_eqv,
                                                                        "USD",
                                                                        datetime.date(2020, 1, 2),
                                                                        datetime.date(2020, 1, 4))
        
        # On 4th of January the unrealized gains are -100 USD
        # self.assertEqual(net_worth_changes_before_realiz[expected_unreal_gains_acc], I("-100 USD"))   
        
        pprint(net_worth_changes_before_realiz)    

        net_worth_changes_after_realiz = get_statement_of_change_in_net_worth_beanq_as_ia(entries_eqv,
                                                                             options_eqv,
                                                                             "USD",
                                                                             datetime.date(2020, 1, 2),
                                                                             datetime.date(2020, 1, 5))
        
        
        # Checking that on 5 January the unrealized gains account is present in the net worth changes, but it is empty
        # The reason it is empty is that the unrealized gains were booked back when they were realized
        self.assertTrue(expected_unreal_gains_acc in net_worth_changes_after_realiz and net_worth_changes_after_realiz[expected_unreal_gains_acc].is_empty())
        
        expected_unreal_gains =  [('Income:Unrealized-Gains:USD-IVV', 
                                   'at_cost', 
                                   'price_change', 
                                   'Assets:Investments',
                                   I("-100 USD")
                                   ),
                                  ('Income:Unrealized-Gains:USD-IVV', 
                                   'at_cost', 
                                   'price_diff', 
                                   'Assets:Investments',
                                   I("100 USD")
                                   )]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
    
    # Converting to the 3rd currency
    @loader.load_doc()
    def test_simple_case_with_cost_and_gain_to_3rd_curr(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Investment
        
        
        2020-01-01 price USD 1 GBP  
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances  
            
        2020-01-02 price IVV 150 GBP
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  -300 USD
            Assets:Investments     2 IVV {150 USD} 
            
        2020-01-04 price IVV 200 GBP
        
        2020-01-05 * "Selling at a new price"
            Assets:Bank:Checking   400 USD 
            Assets:Investments     -2 IVV {150 USD} 
            Income:Investment      -100 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "GBP",
                                                                           None,
                                                                           None,
                                                                           self_testing_mode=True)
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:GBP-IVV', 
                                  'at_cost', 
                                  'price_change',
                                  'Assets:Investments', 
                                  I("-100 GBP")),
                                 
                                 ('Income:Unrealized-Gains:GBP-IVV', 
                                  'at_cost', 
                                  'price_diff', 
                                  'Assets:Investments',
                                  I("100 GBP"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
    
    
    @loader.load_doc()
    def test_simple_case_with_cost_and_gain_mult_curr(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Investment
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 150 USD
        2020-01-02 price HOO 15  USD
            
        2020-01-03 * "Buying at cost IVV"
            Assets:Bank:Checking  -300 USD
            Assets:Investments     2 IVV {150 USD} 
            
        2020-01-03 * "Buying at cost HOO"
            Assets:Bank:Checking  -30 USD
            Assets:Investments     2 HOO {15 USD} 
            
        2020-01-04 price IVV 200 USD
        2020-01-04 price HOO 20 USD
        
        2020-01-05 * "Selling at a new price both IVV and HOO"
            Assets:Bank:Checking   440 USD 
            Income:Investment      -110 USD
            Assets:Investments     -2 IVV {150 USD} @ 200 USD
            Assets:Investments     -2 HOO {15 USD} @ 20 USD
            
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                           None,
                                                                           None,
                                                                           self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:USD-HOO', 
                                  'at_cost', 
                                  'price_change', 
                                  'Assets:Investments',
                                  I("-10 USD")),
                                 
                                ('Income:Unrealized-Gains:USD-HOO', 
                                 'at_cost', 
                                 'price_diff', 
                                 'Assets:Investments',
                                 I("10 USD")),
                                
                                ('Income:Unrealized-Gains:USD-IVV', 
                                 'at_cost', 
                                 'price_change', 
                                 'Assets:Investments',
                                 I("-100 USD")),
                                
                                ('Income:Unrealized-Gains:USD-IVV', 
                                 'at_cost', 
                                 'price_diff', 
                                 'Assets:Investments',
                                 I("100 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
  
    @loader.load_doc()
    def test_simple_case_with_cost_in_unconvert_curr(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Investment
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
         
        ; At this transaction we move the funds from USD to IVV, however at this date there is no price for IVV
        ; As a result this violoates the rules to be able to successfully convert the entries to a single currency    
        ; This can fe fixe, by adding the following line:
        ; 2020-01-02 price IVV 150 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  -300 USD
            Assets:Investments     2 IVV {150 USD} 
            
        2020-01-04 price IVV 200 USD
        
        2020-01-05 * "Selling at a new price"
            Assets:Bank:Checking   400 USD 
            Assets:Investments     -2 IVV {150 USD} @ 200 USD
            Income:Investment      -100 USD
        """
        # printer.print_entries(entries)
        
        with self.assertRaises(RuntimeError) as cm:
            entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "USD",
                                                                            None,
                                                                            None,
                                                                            self_testing_mode=True)
        self.assertIsInstance(cm.exception.__cause__, TransferFundsToFromUnconvertableCommErr)
  
  
    # This tests, that Pad, Balance and Price entries do not appear in converted entries
    @loader.load_doc()
    def test_unneeded_entries(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  100 USD
            Equity:Opening-Balances
            
        2020-01-02 pad Assets:Bank:Checking Expenses:Misc
        2020-01-03 balance Assets:Bank:Checking  90 USD
            
        2020-01-10 price EUR 2 USD
            
        2020-02-02 pad Assets:Bank:Checking Expenses:Misc
        2020-02-03 balance Assets:Bank:Checking  50 USD
        """
    
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2020, 1, 2),
                                                                                      datetime.date(2020, 2, 28),
                                                                                      self_testing_mode=True)
        
        self.assertEqual(len(errors_eqv), 0)
        
        verify_different_objects(entries, entries_eqv) 
        
        # Checking that there are no unneeded entries in the converted entries
        # printing new entries to string
        # Creating io.StringIO object instead of file
        file_replacement = io.StringIO()
        printer.print_entries(entries_eqv, file=file_replacement)
        entries_str = file_replacement.getvalue()
                
        unwanted_entries_re = re.compile(r"\d\d\d\d-\d\d-\d\d\s+(?:pad)", re.IGNORECASE)
        found = unwanted_entries_re.findall(entries_str)
    
        
        self.assertEqual(len(unwanted_entries_re.findall(entries_str)), 0)
  
        
    @loader.load_doc()
    def test_simple_case_with_transaction_no_start_no_end(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Assets:Bank:Checking  1000 EUR
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking  -100 USD
            Expenses:Misc          100 USD
            
        2020-01-02 * "Buying something EUR"
            Assets:Bank:Checking   -100 EUR
            Expenses:Misc           100 EUR
            
            
        2020-01-03 price EUR 2 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      None,
                                                                                      None,
                                                                                      self_testing_mode=True)
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change',
                                  'Assets:Bank:Checking', 
                                  I("450.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
    @loader.load_doc()
    def test_unconvertable_currency_no_transaction(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        ; GPB is unconvertable to EUR, but this is OK as long as there are no transactions to / from this currency and other currencies
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1  100 USD
            Assets:Bank:Checking2  100 GBP 
            Equity:Opening-Balances
            
        2020-01-02 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2020, 1, 2),
                                                                                      datetime.date(2020, 1, 3),
                                                                                      self_testing_mode=True)  
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1',
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        

    @loader.load_doc()
    def test_simple_case_with_transaction_unconvertable_curr(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        ; GPB is unconvertable, but this is OK as long as there are no transactions to / from this correny and other currencies
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1  200 USD
            Assets:Bank:Checking2  200 GBP ; GPB is unconvertable
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking1  -100 USD
            Expenses:Misc           100 USD
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      datetime.date(2020, 1, 2),
                                                                                      datetime.date(2020, 1, 5),
                                                                                      self_testing_mode=True) 
  
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1',
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
   
    @loader.load_doc()
    def test_simple_case_with_transaction_also_in_unconvertable_curr(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1    200 USD
            Assets:Bank:Checking2    200 GBP ; GPB is unconvertable
            Equity:Opening-Balances -200 USD
            Equity:Opening-Balances -200 GBP
            
        2020-01-02 * "Buying something USD"
            Assets:Bank:Checking1  -100 USD
            Expenses:Misc           100 USD
            
        ; This is transaction in unconvertable currency, this shall be OK, as it is not being converted to another currency
        2020-01-02 * "Buying something GBP"
            Assets:Bank:Checking2  -100 GBP
            Expenses:Misc           100 GBP
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      self_testing_mode=True) 
    
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1',
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
        
    # This tests, that there is a balance entry in the unconvertable currency, and it is the first moment of its appearance    
    @loader.load_doc()
    def test_simple_case_with_transaction_also_in_unconvertable_curr_and_balance(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 balance Assets:Bank:Checking2   0 GBP ; GPB is unconvertable and this is the st moment of its appearance
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1    200 USD
            Assets:Bank:Checking2    200 GBP ; GPB is unconvertable
            Equity:Opening-Balances -200 USD
            Equity:Opening-Balances -200 GBP
            
        2020-01-02 * "Buying something USD"
            Assets:Bank:Checking1  -100 USD
            Expenses:Misc           100 USD
            
        ; This is transaction in unconvertable currency, this shall be OK, as it is not being converted to another currency
        2020-01-02 * "Buying something GBP"
            Assets:Bank:Checking2  -100 GBP
            Expenses:Misc           100 GBP
            
        2020-01-03 balance Assets:Bank:Checking2   100 GBP ; again balance in unconvertable currency   
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      self_testing_mode=True) 
    
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1',
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
    @loader.load_doc()
    def test_simple_case_with_transaction_unconvertable_curr_later_convertable(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1  200 USD
            Assets:Bank:Checking2  200 GBP ; GPB is unconvertable at this point
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking1  -100 USD
            Expenses:Misc           100 USD
            
        ; Now GPB becomes convertable, but this is withing the start_date and end_date, hence should cause error
        2020-01-03 price EUR 0.5 GBP
            
        2020-01-03 price EUR 2 USD
        """
        # printer.print_entries(entries)
    
        with self.assertRaises(UnconvertableCommBecomesConvertibleErr):
            entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                        datetime.date(2020, 1, 2),
                                                                                        datetime.date(2020, 1, 5),
                                                                                        self_testing_mode=True) 
        
    @loader.load_doc()
    def test_simple_case_with_transaction_unconvertable_curr_later_convertable_but_outside_dates(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1    200 USD
            Assets:Bank:Checking2    200 GBP ; GPB is unconvertable at this point
            Equity:Opening-Balances -200 USD
            Equity:Opening-Balances -200 GBP
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking1  -100 USD
            Expenses:Misc           100 USD
            
        2020-01-03 price EUR 2 USD
        
        2020-01-06 price EUR 0.5 GBP; Now GPB becomes convertable
        """
    
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                    datetime.date(2020, 1, 2),
                                                                                    datetime.date(2020, 1, 5),
                                                                                    self_testing_mode=True) 

        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1',
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
    @loader.load_doc()
    def test_simple_case_with_transaction_between_convert_and_unconvert_curr(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1   1000 USD
            Assets:Bank:Checking2   1000 GBP ; GPB is unconvertable
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something USD"
            Assets:Bank:Checking1  -100 USD
            Expenses:Misc           100 USD
            
        ; Converting between convertable and unconvertable currency.
        2020-01-02 * "Buying something GBP"
            Assets:Bank:Checking2  -100 USD
            Assets:Bank:Checking2   100 GBP @@ 100 USD
 
            
        2020-01-03 price EUR 2 USD
        """
        # printer.print_entries(entries)
    
        with self.assertRaises(RuntimeError) as cm:
            
            entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                        datetime.date(2020, 1, 2),
                                                                                        datetime.date(2020, 1, 5),
                                                                                        self_testing_mode=True) 
        self.assertIsInstance(cm.exception.__cause__, TransferFundsToFromUnconvertableCommErr)

    # Testing the situation, when there was an unconvertable currency in the past, but at certain point funds are 
    # transfered to / from it, however this is already after the end_date, hence no error should be raised
    @loader.load_doc()
    def test_simple_case_with_transaction_between_convert_and_unconvert_curr_outside_dates(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1   1000 USD
            Assets:Bank:Checking2   1000 GBP ; GPB is unconvertable
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something USD"
            Assets:Bank:Checking1  -100 USD
            Expenses:Misc           100 USD
            
        2020-01-03 price EUR 2 USD
        
        ; Converting between convertable and unconvertable currency.
        2020-01-06 * "Buying something GBP"
            Assets:Bank:Checking2  -100 USD
            Assets:Bank:Checking2   100 GBP @@ 100 USD
        
        """
      
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                    datetime.date(2020, 1, 2),
                                                                                    datetime.date(2020, 1, 5),
                                                                                    self_testing_mode=True) 


        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1',
                                  I("450.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)


    @loader.load_doc()
    def test_simple_case_with_transaction_between_convert_and_unconvert_comm_with_cost(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1   1000 USD
            Assets:Bank:Checking2   1000 GBP ; GPB is unconvertable
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something USD"
            Assets:Bank:Checking1  -100 USD
            Expenses:Misc           100 USD
            
        ; Converting between convertable and unconvertable currency.
        2020-01-02 * "Buying something GBP"
            Assets:Bank:Checking2  -100 USD
            Assets:Bank:Checking2   100 GBP {1 USD}
 
            
        2020-01-03 price EUR 2 USD
        """
        # printer.print_entries(entries)
    
        with self.assertRaises(RuntimeError) as cm:
            
            entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                        datetime.date(2020, 1, 2),
                                                                                        datetime.date(2020, 1, 5),
                                                                                        self_testing_mode=True) 
            
        self.assertIsInstance(cm.exception.__cause__, TransferFundsToFromUnconvertableCommErr)


    # Testing, that it would also work, when providing none-default account for unrealized gains
    @loader.load_doc()
    def test_not_default_unreal_gains_acc(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Equity:Drawings
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking  
            Expenses:Misc        100 USD
            
        2020-01-03 * "Equity withdrawal"
            Assets:Bank:Checking -500 USD  
            Equity:Drawings
            
        2020-01-04 price EUR 2 USD
        """
        # printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                           unreal_gains_p_l_acc="Income:PriceChanges",
                                                                           self_testing_mode=True)

        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:PriceChanges:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking',
                                  I("200.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains, unreal_gain_acc_root="Income:PriceChanges")


    # Testing non-standard account names
    @loader.load_doc()
    def test_simple_non_standard_accounts(self, entries, errors, options):
        """
        option "name_equity" "EquityChanged"
        option "name_expenses" "ExpensesChanged"
        option "name_income" "IncomeChanged"
        option "name_assets" "AssetsChanged"
        option "name_liabilities" "LiabilitiesChanged"
        
        2020-01-01 open AssetsChanged:Bank:Checking 
        2020-01-01 open EquityChanged:Opening-Balances
        2020-01-01 open AssetsChanged:Investments
        2020-01-01 open ExpensesChanged:Misc
        
        2020-01-01 * "Opening Balances"
            AssetsChanged:Bank:Checking  1000 USD
            EquityChanged:Opening-Balances
            
        2020-01-02 price IVV 100 USD
            
        2020-01-03 * "Buying IVV"
            AssetsChanged:Bank:Checking  
            AssetsChanged:Investments 2 IVV @ 100 USD
            
        2020-01-04 price IVV 200 USD
        """
        # printer.print_entries(entries)
    
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, 
                                                                           options, 
                                                                           "USD",
                                                                           None,
                                                                           None,
                                                                           unreal_gains_p_l_acc="IncomeChanged:PriceChanges",
                                                                           self_testing_mode=True)
                
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('IncomeChanged:PriceChanges:USD-IVV', 
                                  'no_cost', 
                                  'price_change', 
                                  'AssetsChanged:Investments',
                                  I("-200 USD"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains, unreal_gain_acc_root="IncomeChanged:PriceChanges")
        
    @loader.load_doc()
    def test_simple_case_with_balance(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
            
        2020-01-04 balance Assets:Bank:Checking  1000 USD    
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      self_testing_mode=True) 

        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking',
                                  I("500.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
        
    @loader.load_doc()
    def test_simple_case_with_balance_tolerance(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
            
        2020-01-04 balance Assets:Bank:Checking  999.00 ~2.0 USD    
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      self_testing_mode=True) 

        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking',
                                  I("500.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)

    @loader.load_doc()
    def test_balance_and_price_same_date(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-03 pad Assets:Bank:Checking Expenses:Misc
            
        2020-01-04 balance Assets:Bank:Checking  500 USD    
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      self_testing_mode=True) 

        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking',
                                  I("500.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
 
    # here testing that the balance entry is on the same date as the price entry
    # this is the issue 7 https://github.com/Ev2geny/evbeantools/issues/7
    @loader.load_doc()
    def test_balance_and_price_same_date(self, entries, errors, options):
        """
        2020-01-01 open Equity:Openning-Balances
        2020-01-01 open Assets:Bank 
        2020-01-01 open Expenses:Misc

        2020-01-01 price EUR                1 USD

        2020-01-01 * "Openning balance"
            Assets:Bank                      100.00 USD
            Equity:Openning-Balances         -100.00 USD


        ; 2020-01-30 pad Assets:Bank  Expenses:Misc

        2020-02-01 price EUR                   2 USD

        2020-02-01 balance Assets:Bank       100.00 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      self_testing_mode=True) 

        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        expected_unreal_gains =[('Income:Unrealized-Gains:EUR-USD', 
                                 'no_cost', 
                                 'price_change', 
                                 'Assets:Bank', I("50.000 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)       
        
    

    # Here we test the sorting order of the entries
    # Our sorting order is a bit stricter than the one in the original beancount:
    # on the same day price entries are always before transactions
    # * unrealized gains transactions are always before normal transactions
    # This is done to be able to see what caused the unrealized gains
    @loader.load_doc()
    def test_sorting_order(self, entries, errors, options):
        """
        option "operating_currency" "BBB" 

        2020-01-01 open Assets:Bank
          seq: "0"
        2020-01-01 open Equity:Opening-Balances
          seq: "1"
        2020-01-01 open Expenses:Food
          seq: "2"


        2020-01-01 * "Opening Balance"
            seq: "3"
            Assets:Bank                100 AAA
            Equity:Opening-Balances   -100 AAA

        2020-01-01 price AAA 1.0 BBB
            seq: "4"

        2020-02-01 * "Buy something"
            seq: "5"
            Assets:Bank                
            Expenses:Food              10 AAA

        2020-02-01 price AAA 2.0 BBB
            seq: "6"
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, 
                                                                           options,
                                                                            self_testing_mode=True) 
        
        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        seq = []
        
        for entry in entries_eqv:
            seq.append(entry.meta.get("seq", -1))
            
        print(seq)
        
        expected_seq = ['0', '1', '2', '4', '3', 
                        -1, # 2020-02-01 open Income:Unrealized-Gains:BBB-AAA. A newly created entry
                        '6', 
                        -1, # 2020-02-01 * "Unrealized gains due to AAA price change from 1.0 to 2.0 BBB (BBB price change from 1 to 0.5 AAA)"
                        '5']
        
        self.assertEqual(seq, expected_seq)
        
        self.assertIsInstance(entries_eqv[7], Transaction)

    # This tests issue 11
    @loader.load_doc()
    def test_small_balance_error(self, entries, errors, options):
        """
        option "operating_currency" "YYY"

        2020-01-01 open Expenses:Misc1
        2020-01-01 open Expenses:Misc2
        2020-01-01 open Assets:Bank


        2020-01-01 price YYY          92.9107970 XXX

        2020-01-01 * "Buying something"
            Expenses:Misc1             3000.00 XXX
            Expenses:Misc2             16570.00 XXX
            Assets:Bank               -19570.00 XXX
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, 
                                                                                      self_testing_mode=True) 

        printer.print_entries(entries_eqv)
        
        verify_different_objects(entries, entries_eqv) 
        
        # expected_unreal_gains =[('Income:Unrealized-Gains:YYY-YYY', 
        #                          None, 
        #                          None, 
        #                          None, I("-0.0000000000000000000000001 YYY"))]
        
        # verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)   


class TestSingCurrConvMultCurrSameAcc(unittest.TestCase):
    """
    Selection of tests, mainly from the TestSingCurrConv, but modifyed for the case to have 
    multiple currencies on the same account
    """

    # Multiple currencies on the same account
    @loader.load_doc()
    def test_simple_case_no_transaction(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking      100 USD
            Assets:Bank:Checking      200 EUR
            Equity:Opening-Balances  
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, 
                                                                           options, 
                                                                           "EUR",
                                                                            None,
                                                                            None,
                                                                            self_testing_mode=True)   
        
        printer.print_entries(entries_eqv)
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking',
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
    
    @loader.load_doc()
    def test_simple_case_no_transaction_with_start_date(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking      100 USD
            Assets:Bank:Checking      200 EUR
            Equity:Opening-Balances  
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, 
                                                                           options, 
                                                                           "EUR",
                                                                           '2020-01-02',
                                                                            None,
                                                                            self_testing_mode=True)   
        
        printer.print_entries(entries_eqv)
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking',
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)
    
    
    @loader.load_doc()
    def test_simple_case_with_transaction(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Assets:Bank:Checking  2000 EUR
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking   -100 USD
            Expenses:Misc           100 USD
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      None,
                                                                                      None,
                                                                                      self_testing_mode=True) 

        printer.print_entries(entries_eqv)
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking', 
                                  I("450.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)


    @loader.load_doc()
    def test_unconvertable_currency_no_transaction(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        ; GPB is unconvertable to EUR
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1  100 USD
            Assets:Bank:Checking1  100 GBP 
            Equity:Opening-Balances
            
        2020-01-03 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, 
                                                                           options, 
                                                                           "EUR",
                                                                           self_testing_mode=True)  

        printer.print_entries(entries_eqv)
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1', 
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)

    # Here we mainly check the equivalent starting transaction
    # TODO: Add more tests, to check that the Equivalent Starting Transaction is correct with correct metadata
    @loader.load_doc()
    def test_unconvertable_currency_no_transaction_with_start_date(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        ; GPB is unconvertable to EUR
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1  100 USD
            Assets:Bank:Checking1  100 GBP 
            Assets:Bank:Checking1  100 YYY 
            Equity:Opening-Balances
            
        2020-01-04 price EUR 2 USD
        """
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, 
                                                                           options, 
                                                                           "EUR",
                                                                           '2020-01-03',
                                                                           self_testing_mode=True)  

        printer.print_entries(entries_eqv)
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1', 
                                  I("50.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)

    @loader.load_doc()
    def test_simple_case_with_transaction_unconvertable_curr(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking1 
        2020-01-01 open Assets:Bank:Checking2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        ; GPB is unconvertable, but this is OK as long as there are no transactions to / from this correny and other currencies
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking1  1000 USD
            Assets:Bank:Checking1  1000 GBP ; GPB is unconvertable
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking1  -100 USD
            Assets:Bank:Checking1  -100 GBP
            Expenses:Misc           
            
        2020-01-03 price EUR 2 USD
        """
        printer.print_entries(entries)
    
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, "EUR",
                                                                                      self_testing_mode=True) 
  
        printer.print_entries(entries_eqv)
        
        expected_unreal_gains = [('Income:Unrealized-Gains:EUR-USD', 
                                  'no_cost', 
                                  'price_change', 
                                  'Assets:Bank:Checking1',
                                  I("450.0 EUR"))]
        
        verify_unrealized_gains(entries_eqv, options_eqv, expected_unreal_gains)



def load_ledger_with_plugin(ledger_str, plugin_str):
    """Loads the ledger string with the plugin string and returns the entries, errors and options
    Errors list will always be empry, as the otherwise function will raise an RuntimeError

    Args:
        ledger_str (_type_): _description_
        plugin_str (_type_): _description_

    Raises:
        RuntimeError: _description_

    Returns:
        _type_: _description_
    """
    
    entries_eqv_plugin, errors_eqv_plug, opts_eqv_plugin = load_string(plugin_str + '\n'+ ledger_str)
    
    if len(errors_eqv_plug) > 0:
        raise RuntimeError(f"Errors returned, when trying to load the file with plugin\n{print_errors_to_string(errors_eqv_plug)}")
    
    return entries_eqv_plugin, errors_eqv_plug, opts_eqv_plugin

class TestSingCurrConvAsPlugin(unittest.TestCase):
    """Tests for the tests, when sing_curr_conv is used as a plugin
    """
    
    maxDiff = None
    
    def assert_pluging_mode_result_the_same_text(self, ledger_str, plugin_str, **kwargs):
        """Helper function to test that when the sing_curr_conv is used as a plugin, the result is the same as when
        the sing_curr_conv is used as a function
        
        Args:
            ledger_str (str): The string with the ledger entries
            plugin_str (str): The string which represents additional text, added to the ledger string, when the 
                 sing_curr_conv is used as a plugin
        """
        
        entries, errors, options = load_string(ledger_str)
        
        entries_eqv_plugin, errors_eqv_plug, opts_eqv_plugin = load_ledger_with_plugin(ledger_str, plugin_str)
        
        # entries_eqv_plugin, errors_eqv_plug, opts_eqv_plugin = load_string(plugin_str + ledger_str)
        
        entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, 
                                                                           self_testing_mode=True, **kwargs)
        
        entries_eqv_plugin_printed = print_entries_to_string(entries_eqv_plugin)
        entries_eqv_printed = print_entries_to_string(entries_eqv)
        
        logger.debug("*********** entries_eqv_plugin_printed ***********")
        logger.debug("\n" + entries_eqv_plugin_printed)
        
        logger.debug("*********** entries_eqv_printed ******************")
        logger.debug("\n" + entries_eqv_printed)
        
        self.assertEqual(entries_eqv_plugin_printed, entries_eqv_printed)
    

    def test_simple_case_with_transaction(self):
        
        plugin_str = """
        plugin "evbeantools.sing_curr_conv" "self_testing_mode=True, target_currency='EUR'"
        """
        
        plugin_str = textwrap.dedent(plugin_str)
        
        ledger_str = """ 
        option "operating_currency" "EUR"      
        
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking -100 USD
            Expenses:Misc         
            
        2020-01-03 price EUR 2 USD
        """
        
        # dedenting the string
        ledger_str = textwrap.dedent(ledger_str)
        
        self.assert_pluging_mode_result_the_same_text(ledger_str, plugin_str)
        
        
    # The same as the previous test, but plugin does not get any configuration string
    def test_simple_case_with_transaction_no_conf_string(self):
        
        plugin_str = """
        plugin "evbeantools.sing_curr_conv" 
        """
        
        plugin_str = textwrap.dedent(plugin_str)
        
        ledger_str = """ 
        option "operating_currency" "EUR"      
        
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking -100 USD
            Expenses:Misc         
            
        2020-01-03 price EUR 2 USD
        """
        
        # dedenting the string
        ledger_str = textwrap.dedent(ledger_str)
        
        self.assert_pluging_mode_result_the_same_text(ledger_str, plugin_str)
        
    def test_simple_case_with_transaction_changed_unreal_g_acc(self):
        
        plugin_str = """
        plugin "evbeantools.sing_curr_conv" "self_testing_mode=True, target_currency='EUR', unreal_gains_p_l_acc = 'Income:PriceChanges'"
        """
        
        plugin_str = textwrap.dedent(plugin_str)
        
        ledger_str = """ 
        option "operating_currency" "EUR"      
        
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking -100 USD
            Expenses:Misc         
            
        2020-01-03 price EUR 2 USD
        """
        
        # dedenting the string
        ledger_str = textwrap.dedent(ledger_str)
        
        self.assert_pluging_mode_result_the_same_text(ledger_str, plugin_str, unreal_gains_p_l_acc = 'Income:PriceChanges')        

    def test_simple_case_with_transactio_no_target_curr(self):
        
        plugin_str = """
        plugin "evbeantools.sing_curr_conv" "self_testing_mode=True"
        """
        
        plugin_str = textwrap.dedent(plugin_str)
        
        ledger_str = """ 
        option "operating_currency" "EUR"      
        
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking -100 USD
            Expenses:Misc         
            
        2020-01-03 price EUR 2 USD
        """
        
        # dedenting the string
        ledger_str = textwrap.dedent(ledger_str)
        
        self.assert_pluging_mode_result_the_same_text(ledger_str, plugin_str)
        
    def test_simple_case_with_transactio_no_target_curr_no_oper_curr(self):
        
        plugin_str = """
        plugin "evbeantools.sing_curr_conv" "self_testing_mode=True"
        """
        
        plugin_str = textwrap.dedent(plugin_str)
        
        ledger_str = """ 
        ; option "operating_currency" "EUR"  <== this is commented out now    
        
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking -100 USD
            Expenses:Misc         
            
        2020-01-03 price EUR 2 USD
        """
        
        # dedenting the string
        ledger_str = textwrap.dedent(ledger_str)
        
        with self.assertRaises(RuntimeError) as cm:
            load_ledger_with_plugin(ledger_str, plugin_str)
            
        # print(cm.exception)
        self.assertIn("'target_currency' is not specified and is not available in the operating currency option", str(cm.exception))

    def test_simple_case_with_transaction_and_start_date_end_date(self):
        
        plugin_str = """
        plugin "evbeantools.sing_curr_conv" "self_testing_mode=True, target_currency='EUR', start_date='2020-01-02', end_date='2020-01-03'"
        """
        
        plugin_str = textwrap.dedent(plugin_str)
        
        ledger_str = """ 
        option "operating_currency" "EUR"      
        
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 * "Buying something"
            Assets:Bank:Checking -100 USD
            Expenses:Misc         
            
        2020-01-03 * "Buying something"
            Assets:Bank:Checking -100 USD
            Expenses:Misc    
            
        2020-01-04 price EUR 2 USD
        """
        
        # dedenting the string
        ledger_str = textwrap.dedent(ledger_str)
        
        self.assert_pluging_mode_result_the_same_text(ledger_str, plugin_str, 
                                                      start_date=datetime.date(2020, 1, 2), 
                                                      end_date=datetime.date(2020, 1, 3))

    # @pytest.mark.order(20)
    def test_simple_case_with_cost_price_change_wrong_cost(self):
        
        plugin_str = """
        plugin "evbeantools.sing_curr_conv" "self_testing_mode=True, target_currency='USD'"
        """
        
        plugin_str = textwrap.dedent(plugin_str)
        
        
        ledger_str = """
        option "operating_currency" "USD"
           
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Assets:Investments
        2020-01-01 open Expenses:Misc
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-02 price IVV 100 USD
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  
            Assets:Investments 2 IVV {150 USD} ; This is a cost, different from the price in the price entry
            
        2020-01-04 price IVV 200 USD
        """
        ledger_str = textwrap.dedent(ledger_str)
        
        self.assert_pluging_mode_result_the_same_text(ledger_str, plugin_str)

    # @pytest.mark.order(30)
    def test_simple_case_with_pad(self):
        
        plugin_str = """
        plugin "evbeantools.sing_curr_conv" "self_testing_mode=True"
        """
        
        ledger_str = """
        
        option "operating_currency" "EUR"
        
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  1000 USD
            Equity:Opening-Balances
            
        2020-01-03 pad Assets:Bank:Checking Expenses:Misc
            
        2020-01-04 balance Assets:Bank:Checking  500 USD    
            
        2020-01-06 price EUR 2 USD
        """
        
        entries_eqv_plugin, errors_eqv_plug, opts_eqv_plugin = load_string(plugin_str + ledger_str)
        
        printer.print_entries(entries_eqv_plugin)


class TestFromCommandLine(unittest.TestCase):
    """Set of tests, to test, that single currency conversion can be run from the command line
    At the moment only will probably work only on Windows 
    """
    #TODO: Add tests for Linux and Mac
    
    
    ledger1 = textwrap.dedent("""
                        option "operating_currency" "EUR" 

                        2020-01-01 open Assets:Bank:Checking 
                        2020-01-01 open Equity:Opening-Balances
                        2020-01-01 open Expenses:Misc

                        2020-01-01 price EUR 1 USD

                        2020-01-01 * "Opening Balances"
                            Assets:Bank:Checking      1000 USD
                            Equity:Opening-Balances  -1000 USD
                        
                        2020-01-02 * "Buying something1"
                            Assets:Bank:Checking      -100 USD
                            Expenses:Misc              100 USD
                        
                        2020-01-03 * "Buying something2"
                            Assets:Bank:Checking      -100 USD
                            Expenses:Misc              100 USD
                        
                            
                        2020-01-04 price EUR 2 USD
                                """)
    
    
    def verify_cmd_conversion(self, ledger_str, cmd_options_str:str, kwargs:dict):
        """
        Helper function to test that the conversion from the command produces the same leger text as the conversion
        from the function
        
        Args:
            ledger_str (str): The string with the ledger entries
            cmd_options_str (str): The string with the command line options
            kwargs (dict): The dictionary with the additional arguments for the get_equiv_sing_curr_entries function
        """
        
        if os.name != 'nt':
            raise unittest.SkipTest("This test at the moment implemented only for Windows")

        ledger = textwrap.dedent(ledger_str)

        # creating  temporary directory
        with tempfile.TemporaryDirectory() as tmpdirname:
            ledger_file = Path(tmpdirname)/"ledger.bean"
            
            output_cmd_converted_ledger = Path(tmpdirname)/"converted_ledger.bean"
            
            with open(ledger_file, "w") as f:
                f.write(ledger)
        
            
            child = wexpect.spawn('cmd', timeout=15)
            child.expect('>')
            child.sendline(f'python -m evbeantools.sing_curr_conv {cmd_options_str} "{ledger_file}" "{output_cmd_converted_ledger}"')
            child.expect(r'Attempting to convert entries to a single currency')
            child.expect(r'File.*has been successfully created')  
            child.expect('>')
            child.sendline('exit')
            child.wait()
            
            with open(output_cmd_converted_ledger, "r") as f:
                converted_via_cmd_ledger_text = f.read()
            
            entries, errors, options = load_string(ledger)
            entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, 
                                                                               self_testing_mode=True, **kwargs)
            
            output_func_converted_ledger = print_entries_to_string(entries_eqv)
            
        self.assertEqual(converted_via_cmd_ledger_text, output_func_converted_ledger)
    
    @pytest.mark.timeout(5)
    @unittest.skipUnless(os.name == 'nt', "This test is only for Windows")
    def test_no_arguments_provided(self):
        
        try:
            child = wexpect.spawn('cmd.exe', timeout = 3)
            child.expect('>', timeout = 3)
            child.sendline('python -m evbeantools.sing_curr_conv')
            child.expect(r'Run the program with -h', timeout = 3)
            
            print("----- captured text -----")
            print(child.before)
            print(child.after)
            child.sendline('exit')
            child.wait()
        except Exception as e:
            raise RuntimeError(f"An error occured. The following text was captured:\n{child.before}\n{child.after}") from e
                
    @unittest.skipUnless(os.name == 'nt', "This test is only for Windows")
    def test_open_in_beanquery(self):
                
        ledger = self.ledger1
        
        with tempfile.NamedTemporaryFile("w", suffix=".bean", delete_on_close=False) as f:
            
            try:            
                f.write(ledger)
                f.close()
                child = wexpect.spawn('cmd', timeout=15)
                child.expect('>')
                child.sendline(f'python -m evbeantools.sing_curr_conv "{f.name}" _bq_')
                child.expect(r'Ready with')  
                child.expect(r'beanquery>')
                child.sendline(r'.exit')
                child.expect('>')
                child.sendline('exit')
                child.wait()
            except Exception as e:
                raise RuntimeError(f"An error occured. The following text was captured:\n{child.before}\n{child.after}") from e
    
    @unittest.skipUnless(os.name == 'nt', "This test is only for Windows")             
    def test_no_arguments(self):
        
        self.verify_cmd_conversion(self.ledger1, "", {})
    
    @unittest.skipUnless(os.name == 'nt', "This test is only for Windows")    
    def test_with_currency_argument(self):
        
        self.verify_cmd_conversion(self.ledger1, "-c EUR", {"target_currency":"EUR"})
    
    @unittest.skipUnless(os.name == 'nt', "This test is only for Windows")        
    def test_with_start_date_agrument(self):
        
        self.verify_cmd_conversion(self.ledger1, '-s 2020-01-02', {"start_date":"2020-01-02"})
    
    @unittest.skipUnless(os.name == 'nt', "This test is only for Windows")    
    def test_with_end_date_agrument(self):
    
        self.verify_cmd_conversion(self.ledger1, '-e 2020-01-02', {"end_date":"2020-01-02"})
    
    @unittest.skipUnless(os.name == 'nt', "This test is only for Windows")    
    def test_with_account_agrument(self):
    
        self.verify_cmd_conversion(self.ledger1, '-a Income:Currency-Gains', 
                                   {"unreal_gains_p_l_acc":"Income:Currency-Gains"})
        
    @unittest.skipUnless(os.name == 'nt', "This test is only for Windows")    
    def test_with_group_p_l(self):
    
        self.verify_cmd_conversion(self.ledger1, '-g', 
                                   {"group_p_l_acc_tr":True})


if __name__ == "__main__":
    logging.getLogger('beanpand.summator').setLevel(logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # Adding file handler
    
    this_file_path = Path(__file__)
    file_for_logging = this_file_path.parent.parent/"tmp"/Path(this_file_path.stem).with_suffix(".log")
    
    # file_for_logging.touch(exist_ok=True)
    
    file_handler = logging.FileHandler(file_for_logging, "a", encoding="utf-8")
    # Creating formatter, which displays time, level, module name, line number and message
    file_handler_formatter = logging.Formatter('%(levelname)s -%(name)s- %(module)s - %(lineno)d - %(funcName)s - %(message)s')
    
    # Creating formatter, which displays logger name, level and message
    # file_handler_formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    
    # Adding formatter to file handler
    file_handler.setFormatter(file_handler_formatter)
    root_logger.addHandler(file_handler)
    logger = logging.getLogger(__name__)

    logger.debug("\n************** Starting unrealized gains testing*******************")
    
    # The below code is for running the individual tests without supressing the print functionality
    
    misc_tests = MiscTests()
    test_sing_curr_conv = TestSingCurrConv()
    test_sing_curr_conv_as_plugin = TestSingCurrConvAsPlugin()
    test_sing_curr_conv_mult_curr_same_Acc = TestSingCurrConvMultCurrSameAcc()
    test_from_command_line = TestFromCommandLine()
    
    # test_from_command_line.test_open_in_beanquery()
    # test_simple_case_with_pad()
    # test_sing_curr_conv.test_simple_case_with_transaction_also_in_unconvertable_curr_and_balance()
    # test_no_arguments_provided()
    # test_from_command_line.test_no_arguments_provided()
    # test_open_in_beanquery()
    # test_from_command_line.test_open_in_beanquery()
    
    # test_sing_curr_conv_mult_curr_same_Acc.test_unconvertable_currency_no_transaction_with_start_date()
    
    # test_sing_curr_conv.test_sorting_order()
    # test_sing_curr_conv.test_small_balance_error()