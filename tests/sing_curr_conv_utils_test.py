import unittest
import datetime
from pprint import pprint

import beancount
from beancount import loader
from beancount.parser import printer

from evbeantools.summator import InventoryAggregator
from evbeantools.sing_curr_conv_utils import beanq_2_invent_agg, get_net_worth_via_beanq_as_ia
from evbeantools.sing_curr_conv_utils import EntriesUnchangedChecker, get_statement_of_change_in_net_worth_beanq_as_ia


class Test_beanq_2_invent_agg(unittest.TestCase):
    
    @loader.load_doc()
    def test_normal_case(self, entries, _, options):
        """ 
        2020-01-01 open Assets:Bank:Checking
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  100 USD
            Equity:Opening-Balances
        """
        
        sql_query = r"""
            SELECT account, sum(position)
            """
        
        inv_agg = beanq_2_invent_agg(entries, options, sql_query)
        
        expected_inv_agg = InventoryAggregator({"Assets:Bank:Checking": "100 USD",
                                                "Equity:Opening-Balances": "-100 USD"})
        
        self.assertEqual(inv_agg, expected_inv_agg)
        
    @loader.load_doc()
    def test_empty_result(self, entries, _, options):
        """ 
        2020-01-01 open Assets:Bank:Checking
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  100 USD
            Equity:Opening-Balances
        """
        
        sql_query = r"""
            SELECT account, sum(position)
            WHERE account = "Expenses:Misc"
            """
        
        inv_agg = beanq_2_invent_agg(entries, options, sql_query)
        
        expected_inv_agg = InventoryAggregator()
        
        self.assertEqual(inv_agg, expected_inv_agg)
        
    @loader.load_doc()
    def test_wrong_number_columns(self, entries, _, options):
        """ 
        2020-01-01 open Assets:Bank:Checking
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  100 USD
            Equity:Opening-Balances
        """
        
        sql_query = r"""
            SELECT account, sum(position), cost(position)
            """
        
        with self.assertRaises(AssertionError):
            inv_agg = beanq_2_invent_agg(entries, options, sql_query)
            
    @loader.load_doc()
    def test_wrong_col_types(self, entries, _, options):
        """ 
        2020-01-01 open Assets:Bank:Checking
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  100 USD
            Equity:Opening-Balances
        """
        
        sql_query = r"""
            SELECT account, date
            """
        # inv_agg = beanq_2_invent_agg(entries, options, sql_query)
        
        with self.assertRaises(AssertionError):
            inv_agg = beanq_2_invent_agg(entries, options, sql_query)
             

class TestBeanqFunc(unittest.TestCase):
    
    @loader.load_doc()
    def test_get_converted_net_worth_via_beanq_as_ia(self, entries, _, options):
        """
        2020-01-01 open Assets:Bank:Checking
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  100 USD
            Assets:Bank:Checking  200 EUR
            Assets:Bank:Checking  300 TUG
            Equity:Opening-Balances
            
        2020-01-01 price USD 2 EUR
        """
        
        calculated_res = get_net_worth_via_beanq_as_ia (entries, options, "USD", datetime.date(2020, 1, 2))
        
        expected_result = InventoryAggregator({"Assets:Bank:Checking": "200 USD, 300 TUG"})
        
        self.assertEqual(calculated_res, expected_result)
        
    @loader.load_doc()
    def test_get_converted_p_and_l_beanq_as_ia(self, entries, _, options):
        """
        2020-01-01 open Assets:Bank:Checking
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Misc
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking  100 USD
            Assets:Bank:Checking  200 EUR
            Assets:Bank:Checking  300 TUG
            Equity:Opening-Balances
            
        2020-01-02 price USD 2 EUR
        
        2020-01-03 * "buying something"
            Expenses:Misc 100 USD
            Assets:Bank:Checking
            
        2020-01-04 * "Getting income"
            Income:Misc
            Assets:Bank:Checking 200 EUR
        """
        
        calculated_res = get_statement_of_change_in_net_worth_beanq_as_ia(entries, options, "USD", datetime.date(2020, 1, 2), datetime.date(2020, 1, 5))
        
        expected_result = InventoryAggregator({'Expenses:Misc': "100 USD",
                                               'Income:Misc': "-100 USD"})
         
        self.assertEqual(calculated_res, expected_result)
        
        
class TestEntriesUnchangedChecker(unittest.TestCase):

    def test_simpl_array(self):
        arr = [1, 2, 3]
        arr2 = [1, 2, 3]
        checker = EntriesUnchangedChecker()
        checker.load_original_entries(arr)
        checker.confirm_entries_unchanged(arr2)

    @loader.load_doc()
    def test_simple_case_unchanged(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking      100 USD
            Equity:Opening-Balances  -100 USD
            
        2020-01-03 price EUR 2 USD
        """
        
        checker = EntriesUnchangedChecker()
        checker.load_original_entries(entries)
        checker.confirm_entries_unchanged(entries)
        
    @loader.load_doc()
    def test_simple_case_changed(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank:Checking 
        2020-01-01 open Equity:Opening-Balances
        
        2020-01-01 price EUR 1 USD
        
        2020-01-01 * "Opening Balances"
            Assets:Bank:Checking      100 USD
            Equity:Opening-Balances  -100 USD
            
        2020-01-03 price EUR 2 USD
        """
        
        checker = EntriesUnchangedChecker()
        checker.load_original_entries(entries)
        
        entries[0].meta["test_123"] = "test_123"
        
        printer.print_entries(entries)
        
        # This will check, that the error is raised, and it contains the test_123 string
        with self.assertRaisesRegex(RuntimeError, r"test_123"):
            checker.confirm_entries_unchanged(entries)


    
if __name__ == "__main__":
    
    
    # test_cl = TestBeanqFunc()
    
    # test_cl.test_get_converted_p_and_l_beanq_as_ia()
    
    tst = TestEntriesUnchangedChecker()
    # tst.test_simple_case_changed()
    
        
        