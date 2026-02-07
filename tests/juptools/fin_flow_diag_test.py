import unittest
from decimal import Decimal

from beancount import loader

from evbeantools.juptools.fin_flow_diag import get_meshed_postings_data, get_meshed_postings_data_for_entries, get_transaction_data

class Test_get_transaction_data(unittest.TestCase):
    
    @loader.load_doc()
    def test_simple_case(self, entries, errors, options):
        """
        2021-01-01 open Assets:Bank:Acc1 
        2021-01-01 open Assets:Bank:Acc2
        
        2021-01-01 * "Test Transaction"
            Assets:Bank:Acc1    100 USD
            Assets:Bank:Acc2   -100 USD
        """
        
        tr_data = get_transaction_data(entries[2], "USD")
        
        self.assertEqual(tr_data, 
                         {'Assets:Bank:Acc1': Decimal('100'), 'Assets:Bank:Acc2': Decimal('-100')}
                         )
        
    @loader.load_doc()
    def test_mult_postings(self, entries, errors, options):
        """
        2021-01-01 open Assets:Bank:Acc1 
        2021-01-01 open Assets:Bank:Acc2
        
        2021-01-01 * "Test Transaction"
            Assets:Bank:Acc1    100 USD
            Assets:Bank:Acc1    100 USD
            Assets:Bank:Acc2   -200 USD
        """
        
        tr_data = get_transaction_data(entries[2], "USD")
        
        self.assertEqual(tr_data, 
                         {'Assets:Bank:Acc1': Decimal('200'), 'Assets:Bank:Acc2': Decimal('-200')}
                         )
    
    @loader.load_doc()
    def test_has_price(self, entries, errors, options):
        """
        2021-01-01 open Assets:Bank:Acc1 
        2021-01-01 open Assets:Bank:Acc2
        
        2021-01-01 * "Test Transaction"
            Assets:Bank:Acc1    200 USD @@ 100 EUR
            Assets:Bank:Acc2   -100 EUR
        """
        
        with self.assertRaises(ValueError):
            tr_data = get_transaction_data(entries[2], "USD")
        
    @loader.load_doc()
    def test_has_cost(self, entries, errors, options):
        """
        2021-01-01 open Assets:Bank:Acc1 
        2021-01-01 open Assets:Bank:Acc2
        
        2021-01-01 * "Test Transaction"
            Assets:Bank:Acc1    10 IVV {100 USD}
            Assets:Bank:Acc2   -1000 USD
        """
        
        with self.assertRaises(ValueError):
            tr_data = get_transaction_data(entries[2], "USD")
            
    @loader.load_doc()
    def test_other_currencies(self, entries, errors, options):
        """
        2021-01-01 open Assets:Bank:Acc1 
        2021-01-01 open Assets:Bank:Acc2
        
        2021-01-01 * "Test Transaction"
            Assets:Bank:Acc1    100 EUR
            Assets:Bank:Acc2   -100 EUR
        """

        tr_data = get_transaction_data(entries[2], "USD")
        
        self.assertEqual(tr_data, None)
        
class Test_get_meshed_postings_data(unittest.TestCase):
    
    def test_simple_case(self):
        
        postings_data = {
            'Assets:Bank:Acc1': Decimal('100'),
            'Assets:Bank:Acc2': Decimal('-100')
        }
        
        meshed_data = get_meshed_postings_data(postings_data)
        
        self.assertEqual(meshed_data, 
                         {('Assets:Bank:Acc2', 'Assets:Bank:Acc1'): Decimal('100')}
                         )    
        
    def test_one_to_many(self):
    
        postings_data = {
            'Assets:Bank': Decimal('-180'),
            'Expenses:Cat1': Decimal('60'),
            'Expenses:Cat2': Decimal('120')
        }
        
        meshed_data = get_meshed_postings_data(postings_data)
        
        self.assertEqual(meshed_data, 
                         {('Assets:Bank', 'Expenses:Cat1'): Decimal('60'),
                          ('Assets:Bank', 'Expenses:Cat2'): Decimal('120')}
                         )
        
    def test_many_to_many(self):
    
        postings_data = {
            'Assets:Bank1': Decimal('-180'),
            'Assets:Bank2': Decimal('-1800'),
            'Expenses:Cat1': Decimal('660'),
            'Expenses:Cat2': Decimal('1320')
        }
        
        meshed_data = get_meshed_postings_data(postings_data)
        
        print(meshed_data)
        
        self.assertEqual(meshed_data, 
                         {('Assets:Bank1', 'Expenses:Cat1'): Decimal('60'), 
                          ('Assets:Bank1', 'Expenses:Cat2'): Decimal('120'), 
                          ('Assets:Bank2', 'Expenses:Cat1'): Decimal('600'), 
                          ('Assets:Bank2', 'Expenses:Cat2'): Decimal('1200')}
                         )
                         
class Test_get_meshed_postings_data_for_entries(unittest.TestCase):
    
    @loader.load_doc()
    def test_simple_case(self, entries, errors, options):
        """
        2021-01-01 open Assets:Bank1 
        2021-01-01 open Expenses:Cat1
        
        2021-01-01 * "Test Transaction"
            Assets:Bank1    -200 USD
            Expenses:Cat1    200 USD            
        """
        
        meshed_data = get_meshed_postings_data_for_entries(entries, "USD")
        
        print(meshed_data)
        
        self.assertEqual(meshed_data,
                         {('Assets:Bank1', 'Expenses:Cat1'): Decimal('200')}
                         )            
        
    @loader.load_doc()
    def test_mult_postings(self, entries, errors, options):
        """
        2021-01-01 open Assets:Bank1 
        2021-01-01 open Expenses:Cat1
        2021-01-01 open Expenses:Cat2
        
      
            
        2021-01-02 * "Test Transaction 2"
            Assets:Bank1    -500 USD
            Expenses:Cat1    200 USD  
            Expenses:Cat2    300 USD   
            
        """
        
        meshed_data = get_meshed_postings_data_for_entries(entries, "USD")
        
        print(meshed_data)
        
        self.assertEqual(meshed_data,
                         {('Assets:Bank1', 'Expenses:Cat1'): Decimal('200'), 
                          ('Assets:Bank1', 'Expenses:Cat2'): Decimal('300')}
                         )     
        
    @loader.load_doc()
    def test_mult_transactions(self, entries, errors, options):
        """
        2021-01-01 open Assets:Bank1 
        2021-01-01 open Expenses:Cat1
        2021-01-01 open Expenses:Cat2
        2021-01-01 open Expenses:Cat3
      
        2021-01-02 * "Test Transaction 2"
            Assets:Bank1    -500 USD
            Expenses:Cat1    200 USD  
            Expenses:Cat2    300 USD   
            
        2021-01-02 * "Test Transaction 3"
            Assets:Bank1    -10 USD
            Expenses:Cat1    10 USD
            
        2021-01-03 * "Test Transaction 3"
            Assets:Bank1    -1 USD
            Expenses:Cat3    1 USD
        """
        
        meshed_data = get_meshed_postings_data_for_entries(entries, "USD")
        
        print(meshed_data)
        
        self.assertEqual(meshed_data,
                         {('Assets:Bank1', 'Expenses:Cat1'): Decimal('210'), 
                          ('Assets:Bank1', 'Expenses:Cat2'): Decimal('300'), 
                          ('Assets:Bank1', 'Expenses:Cat3'): Decimal('1')}
                         )   
        
if __name__ == '__main__':
    test_get_transaction_data = Test_get_transaction_data()
    test_get_meshed_postings_data = Test_get_meshed_postings_data()
    test_get_meshed_postings_data_for_entries = Test_get_meshed_postings_data_for_entries()
    
    # test_get_meshed_postings_data.test_many_to_many()
    
    test_get_meshed_postings_data_for_entries.test_mult_transactions()