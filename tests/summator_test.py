import unittest
import copy
import textwrap
import datetime
from pprint import pprint
import logging
from pathlib import Path

from beancount.core.amount import Amount as A
from beancount.core.account import Account
from beancount.core import inventory
from beancount.core.number import D

from beancount.loader import load_string
from beancount.core.prices import build_price_map, PriceMap
from beancount import loader

from beancount.parser import printer



from evbeantools.summator import InventoryAggregator, BeanSummator

I = inventory.from_string

def build_price_map_from_bean_string(bean_str: str):
    
    # loading bean_str into a beancount file
    entries, errors, options_map = load_string(bean_str)
    
    print(entries)
    
    price_map = build_price_map(entries)
    
    return price_map


class TestInventoryAggregator(unittest.TestCase):
    def test_init_empty(self):
        empty_aggregator = InventoryAggregator()
        self.assertIsInstance(empty_aggregator, InventoryAggregator)
        self.assertFalse(empty_aggregator)  # It should be empty

    def test_init_with_dict(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "100.00 USD", 
                                        "Assets:Bank2": "200.00 USD"})
        self.assertIsInstance(inv_agg, InventoryAggregator)
        self.assertTrue(inv_agg)  # It should not be empty
        
        self.assertEqual(inv_agg["Assets:Bank1"], I("100.00 USD"))
        
        pprint(inv_agg)
        
        print(inv_agg.get("Assets:Bank3"))


    def test_init_with_dict_with_cost(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "2 IVV {100 USD}"})

        print(inv_agg)
                                      
        self.assertIsInstance(inv_agg, InventoryAggregator)
        self.assertTrue(inv_agg) 
        
        self.assertEqual(inv_agg["Assets:Bank1"], I("2 IVV {100 USD}"))

    def test_init_with_dict_with_cost_and_cost_date(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "2 IVV {100 USD, 2020-01-01}"})

        print(inv_agg)
                                      
        self.assertIsInstance(inv_agg, InventoryAggregator)
        self.assertTrue(inv_agg) 
        
        self.assertEqual(inv_agg["Assets:Bank1"], I("2 IVV {100 USD, 2020-01-01}"))    
    

    def test_sum_all(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "100.00 USD", 
                                            "Assets:Bank2": "200.00 USD",
                                            "Assets:Bank3": "300.00 EUR"})

        total_inv = inv_agg.sum_all()
        self.assertEqual(total_inv, inventory.from_string("300.00 USD, 300.00 EUR"))  # Assuming str representation is like this
        
    def test_sum_all_with_cost(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "2 IVV", 
                                        "Assets:Bank2": "2 IVV {100 USD}",
                                        "Assets:Bank3": "2 IVV {100 USD}",
                                         "Assets:Bank4": "2 IVV {100 USD, 2020-01-01}"})

        total_inv = inv_agg.sum_all()
        
        print(total_inv)
        
        self.assertEqual(total_inv, 
                         inventory.from_string("2 IVV, 2 IVV {100 USD, 2020-01-01}, 4 IVV {100 USD}"))  

    def test_subtraction(self):
        inv_agg1 = InventoryAggregator({"Assets:Bank1": "100.00 USD", 
                                            "Assets:Bank2": "200.00 USD",
                                            "Assets:Bank3": "300.00 EUR"})
        
        inv_agg2 = InventoryAggregator({"Assets:Bank1": "50.00 USD", 
                                    "Assets:Bank2": "200.00 USD",
                                    "Assets:Bank3": "300.00 EUR"})

        result_agg = inv_agg1 - inv_agg2
        
        inv_agg_expected = InventoryAggregator({"Assets:Bank1": "50.00 USD", 
                                                    "Assets:Bank2": "",
                                                    "Assets:Bank3": ""})
        
        self.assertEqual(result_agg, inv_agg_expected)

    def test_copy(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "100.00 USD", 
                                            "Assets:Bank2": "200.00 USD",
                                            "Assets:Bank3": "300.00 EUR"})
        
        inv_agg_copy = copy.copy(inv_agg)
        
        self.assertEqual(inv_agg_copy, inv_agg)
        
        self.assertIsNot(inv_agg_copy, inv_agg)
            
    def test_clean_empty(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "100.00 USD", 
                                            "Assets:Bank2": "",
                                            "Assets:Bank3": "300.00 EUR"})
        
        cleaned_agg = inv_agg.clean_empty()
        
        inv_agg_expected = InventoryAggregator({"Assets:Bank1": "100.00 USD", 
                                                    "Assets:Bank3": "300.00 EUR"})
        
        self.assertEqual(cleaned_agg, inv_agg_expected)
        
    def test_is_empty(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "", 
                                            "Assets:Bank2": "",
                                            "Assets:Bank3": ""})
        
        self.assertTrue(inv_agg.is_empty())
        
        inv_agg = InventoryAggregator({"Assets:Bank1": "30 USD", 
                                    "Assets:Bank2": "",
                                    "Assets:Bank3": ""})
        
        self.assertFalse(inv_agg.is_empty())
        
    def test_convert(self):
        bean_str = """
        2020-01-01 price EUR 1 USD
        2020-01-02 price EUR 2 USD
        """
        bean_str = textwrap.dedent(bean_str)
        
        price_map = build_price_map_from_bean_string(bean_str)
        
        inv_agg=InventoryAggregator({"Assets:Bank1": "100.00 USD, 200.00 HOO"})
        
        with self.subTest("Test conversion on the 1st price date"):
            
            converted_inv_agg = inv_agg.convert("EUR", price_map, datetime.date(2020,1,1))
            
            inv_agg_expected = InventoryAggregator({"Assets:Bank1": "100.00 EUR, 200.00 HOO"})
            
            self.assertEqual(converted_inv_agg, inv_agg_expected)
        
        # converted_inv_agg = inv_agg.convert("EUR", price_map, datetime.date(2020,1,1))
        
        # inv_agg_expected = InventoryAggregator({"Assets:Bank1": "100.00 EUR, 200.00 HOO"})
        
        # self.assertEqual(converted_inv_agg, inv_agg_expected)
        
        with self.subTest("Test conversion on the 2nd price date"):
            
            converted_inv_agg = inv_agg.convert("EUR", price_map, datetime.date(2020,1,2))
            
            inv_agg_expected = InventoryAggregator({"Assets:Bank1": "50.00 EUR, 200.00 HOO"})
            
            self.assertEqual(converted_inv_agg, inv_agg_expected)
            
        with self.subTest("Test conversion on a date after the last price date"):
            
            converted_inv_agg = inv_agg.convert("EUR", price_map, datetime.date(2020,1,3))
            
            inv_agg_expected = InventoryAggregator({"Assets:Bank1": "50.00 EUR, 200.00 HOO"})
            
            self.assertEqual(converted_inv_agg, inv_agg_expected)
            
        with self.subTest("Test conversion on a date before the first price date"):
            
            converted_inv_agg = inv_agg.convert("EUR", price_map, datetime.date(2019,12,31))
            
            inv_agg_expected = InventoryAggregator({"Assets:Bank1": "100.00 USD, 200.00 HOO"})
            
            self.assertEqual(converted_inv_agg, inv_agg_expected)
            
        with self.subTest("Test conversion with no date"):
            
            converted_inv_agg = inv_agg.convert("EUR", price_map)
            
            inv_agg_expected = InventoryAggregator({"Assets:Bank1": "50.00 EUR, 200.00 HOO"})
            
            self.assertEqual(converted_inv_agg, inv_agg_expected)
        
    def test_convert_with_cost(self):
        bean_str = """
        2020-01-02 price IVV 100 USD
        """
        bean_str = textwrap.dedent(bean_str)
        
        price_map = build_price_map_from_bean_string(bean_str)
        
        inv_agg = InventoryAggregator({"Assets:Bank1": "1.0 IVV {100 USD}"})
        
        inv_agg_converted = inv_agg.convert("USD", price_map, datetime.date(2020, 1, 2))
        
        print(inv_agg.convert("USD", price_map, datetime.date(2020, 1, 2)))
        
        # The dummy '1 REMOVEDCOST' is added, as it is the one with cost
        inv_agg_expected = InventoryAggregator({'Assets:Bank1': "100.0 USD {1 REMOVEDCOST}"})
        
        self.assertEqual(inv_agg_converted, inv_agg_expected)
        
    def test_convert_with_cost_and_no_cost_the_same_commodity(self):
        bean_str = """
        2020-01-02 price IVV 100 USD
        """
        bean_str = textwrap.dedent(bean_str)
        
        price_map = build_price_map_from_bean_string(bean_str)
        
        inv_agg = InventoryAggregator({"Assets:Bank1": "2.0 IVV, 1.0 IVV {100 USD}"})
        
        inv_agg_converted = inv_agg.convert("USD", price_map, datetime.date(2020, 1, 2))
        
        print(inv_agg.convert("USD", price_map, datetime.date(2020, 1, 2)))
        
        inv_agg_expected = InventoryAggregator({'Assets:Bank1': "200.0 USD, 100.0 USD {1 REMOVEDCOST})"})
        
        self.assertEqual(inv_agg_converted, inv_agg_expected)
        
    def test_get_sorted(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "100.00 USD, 50 EUR", 
                                    "Assets:Aank2": "200.00 USD",
                                    "Assets:Cank3": "300.00 EUR"})
        
        expected = InventoryAggregator({"Assets:Aank2": "200.00 USD",
                                              "Assets:Bank1": "100.00 USD, 50 EUR",  
                                              "Assets:Cank3": "300.00 EUR"})
        
        self.assertEqual(inv_agg, expected)

    def test_is_small(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "0.000000000001 USD, 0.000000000001 EUR", 
                                       "Assets:Bank2": "0.000000000001 USD",
                                       "Assets:Bank3": "0.000000000001 USD"})
        
        tolerance_enough = D("0.00000000001")
        
        self.assertTrue(inv_agg.is_small(tolerance_enough))
        
        tolerance_not_enough = D("0.0000000000001")
        
        self.assertFalse(inv_agg.is_small(tolerance_not_enough))

    def test_clean_small(self):
        inv_agg = InventoryAggregator({"Assets:Bank1": "0.000000000001 USD, 0.000000000001 EUR", 
                                       "Assets:Bank2": "0.000000000001 USD",
                                       "Assets:Bank3": "1.0 USD"})
        
        tolerance = D("0.0001")
        
        cleaned_inv_agg = inv_agg.clean_small(tolerance)
        
        expected = InventoryAggregator({"Assets:Bank3": "1.0 USD"})
        
        self.assertEqual(cleaned_inv_agg, expected)
class TestBeanSummator(unittest.TestCase):
    @loader.load_doc()
    def test_normal_cases(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank1
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Salary
        
        2020-01-02 * "Initial Balance"
          Assets:Bank1  100.00 USD
          Equity:Opening-Balances -100.00 USD
        
        2020-01-04 * "Salary"
          Assets:Bank1  500.00 USD
          Income:Salary -500.00 USD
          
        2020-01-05 * "Expenses 1"
          Assets:Bank1  -100.00 USD
          Expenses:Misc  100.00 USD
          
        2020-01-05 * "Expenses 2"
          Assets:Bank1  -100.00 USD
          Expenses:Misc  100.00 USD
          
        2020-01-06 price EUR 2 USD  
        2020-01-06 * "Expenses 3"
           Assets:Bank1  -100.00 USD
          Expenses:Misc  100.00 USD
          
        """
        
        logger = logging.getLogger()
        
        bean_summator = BeanSummator(entries, 
                                     options,
                                     accounts_re ="Assets:Bank1")
        
        
        # Testing with the date before any entry date
        test_date = datetime.date(2019,1,1)
        logger.debug(f"Callling sum_till_date {test_date}")
        result = bean_summator.sum_till_date(test_date)
        self.assertTrue(result.is_empty())
        pprint(result)
        
        # Testing on the date, where there are entries, but no transactions
        test_date = datetime.date(2020,1,1)
        logger.debug(f"Callling sum_till_date {test_date}")
        result = bean_summator.sum_till_date(test_date)
        self.assertTrue(result.is_empty())
        pprint(result)
        
        # Testing one transaction
        test_date = datetime.date(2020,1,2)
        logger.debug(f"Callling sum_till_date {test_date}")
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "100.00 USD"})
        self.assertEqual(result, expected)
        pprint(result)
        
        # Testing on the date, between entries
        # Shall return previous result
        test_date = datetime.date(2020,1,3)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "100.00 USD"})
        self.assertEqual(result,expected)
        pprint(result)
        
        # Testing, that new transactions are taken into account
        test_date = datetime.date(2020,1,4)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "600.00 USD"})
        self.assertEqual(result,expected)
        pprint(result)
        
       # Testing, that calling result on the same date several time produces the same result
        test_date = datetime.date(2020,1,4)
        result = bean_summator.sum_till_date(test_date)
        result = bean_summator.sum_till_date(test_date)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "600.00 USD"})
        self.assertEqual(result,expected)
        pprint(result)
        
        # Testing on the date, where there are several transactions
        # All of them shall be taken into account
        test_date = datetime.date(2020,1,5)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "400.00 USD"})
        self.assertEqual(result,expected)
        pprint(result)
        
        # Testing on the date, where there are not only transactions
        # This shall not influence the running sum
        test_date = datetime.date(2020,1,6)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "300.00 USD"})
        self.assertEqual(result,expected)
        pprint(result)
        
        # Testing of the date after the last entry
        # This shall return the last result
        test_date = datetime.date(2020,1,8)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "300.00 USD"})
        self.assertEqual(result,expected)
        pprint(result)
        
        # Testing the that the date after last entry cal be called several times
        # This shall return the last result
        test_date = datetime.date(2020,1,8)
        result = bean_summator.sum_till_date(test_date)
        result = bean_summator.sum_till_date(test_date)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "300.00 USD"})
        self.assertEqual(result,expected)
        pprint(result)
    
    @loader.load_doc()    
    def test_calling_dates_in_wrong_sequence(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank1
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Salary
        
        2020-01-02 * "Initial Balance"
          Assets:Bank1  100.00 USD
          Equity:Opening-Balances -100.00 USD
        
        2020-01-04 * "Salary"
          Assets:Bank1  500.00 USD
          Income:Salary -500.00 USD
        """
        
        logger = logging.getLogger()
        
        bean_summator = BeanSummator(entries, 
                                     options,
                                     accounts_re ="Assets:Bank1")
        
        test_date = datetime.date(2020,1,4)
        result = bean_summator.sum_till_date(test_date)
        
        test_date = datetime.date(2020,1,2)
        # This shall raise an error, as the BeanSummator does not allow requesting
        # sum for the date before the one already processed
        with self.assertRaises(ValueError):
            result = bean_summator.sum_till_date(test_date)
        
    @loader.load_doc() 
    def test_multiple_currencies(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank1
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Salary
        
        2020-01-02 * "Initial Balance"
          Assets:Bank1  100.00 USD
          Equity:Opening-Balances -100.00 USD
        
        2020-01-04 * "Salary"
          Assets:Bank1  500.00 EUR
          Income:Salary -500.00 EUR
        """
        
        bean_summator = BeanSummator(entries, 
                                options,
                                accounts_re ="Assets:Bank1")
        
        # Testing on the date, where there are entries, but no transactions
        test_date = datetime.date(2020,1,4)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets:Bank1': "100.00 USD, 500 EUR"})
        self.assertEqual(result,expected)
        pprint(result)
        
    @loader.load_doc() 
    def test_num_acc_components_from_root(self, entries, errors, options):
        """
        2020-01-01 open Assets:Bank1
        2020-01-01 open Assets:Bank2
        2020-01-01 open Equity:Opening-Balances
        2020-01-01 open Expenses:Misc
        2020-01-01 open Income:Salary
        
        2020-01-02 * "Initial Balance"
          Assets:Bank1  100.00 USD
          Equity:Opening-Balances -100.00 USD
        
        2020-01-04 * "Salary"
          Assets:Bank2  100.00 USD
          Income:Salary -100.00 USD
        """
        
        bean_summator = BeanSummator(entries, 
                                options,
                                accounts_re ="Assets",
                                num_acc_components_from_root = 1)
        
        # Testing on the date, where there are entries, but no transactions
        test_date = datetime.date(2020,1,4)
        result = bean_summator.sum_till_date(test_date)
        expected = InventoryAggregator({'Assets': "200.00 USD"})
        self.assertEqual(result,expected)
        pprint(result)
        
if __name__ == "__main__":
    
    # inv_agg1 = InventoryAggregator({"Assets:Bank1": "100.00 USD, 50 EUR", 
    #                                     "Assets:Bank2": "200.00 USD",
    #                                     "Assets:Bank3": "300.00 EUR",
    #                                     "Assets:Bank4": "500 RUB"})
    
    # inv_agg2 = InventoryAggregator({"Assets:Bank1": "50.00 USD, 100.00 RUB", 
    #                             "Assets:Bank2": "200.00 USD",
    #                             "Assets:Bank3": "300.00 EUR",
    #                             "Assets:Bank5": "700 TUG"})
    
    # inv_agg3 = InventoryAggregator({"Assets:Bank1": "100.00 USD, 50 EUR", 
    #                                     "Assets:Aank2": "200.00 USD",
    #                                     "Assets:Cank3": "300.00 EUR"})
    
    # pprint(inv_agg3.get_sorted())
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # Adding file handler
    
    this_file_path = Path(__file__)
    file_for_logging = this_file_path.parent/"tmp"/Path(this_file_path.stem).with_suffix(".log")
    
    file_handler = logging.FileHandler("summator_test.log", encoding="utf-8")
    # Creating formatter, which displays time, level, module name, line number and message
    file_handler_formatter = logging.Formatter('%(levelname)s - %(module)s - %(lineno)d - %(funcName)s - %(message)s')
    # Adding formatter to file handler
    file_handler.setFormatter(file_handler_formatter)
    
    root_logger.addHandler(file_handler)
    
    logger = logging.getLogger(__name__)
    
    logger.debug("\n*****************Starting test****************")
    
    test_class_summator = TestBeanSummator()
    
    test_class_inv_agg = TestInventoryAggregator()
    
    # test_class_inv_agg.test_convert_with_cost_and_no_cost_the_same_commodity()
    
