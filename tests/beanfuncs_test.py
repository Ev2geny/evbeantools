import unittest
import textwrap
import io

from beancount import loader
from beancount.core.data import Transaction
from beancount.core.amount import Amount
from beancount.parser import printer
from beancount.core import compare

from evbeantools.beanfuncs import split_posting
from evbeantools.sing_curr_conv_utils import EntriesUnchangedChecker


class Test_split_posting(unittest.TestCase):
    
    def compare_entries(self, entries_actual, entries_expected):
        
        same, missing1, missing2 = compare.compare_entries(entries_actual, entries_expected)
        
        if same:
            print("Entries are the same. Congratulations.")
        else:
            # creating iostring to be used as a file-like object
            file_like_obj = io.StringIO()
            
            print(file=file_like_obj)
            print("\n\nMissing from actual:", file=file_like_obj)
            for entry in missing1:
                print(entry, file=file_like_obj)
                print(compare.hash_entry(entry), file=file_like_obj)
                print(printer.format_entry(entry), file=file_like_obj)
                print(file=file_like_obj)

            print("\n\nMissing from expected:", file=file_like_obj)
            for entry in missing2:
                print(entry, file=file_like_obj)
                print(compare.hash_entry(entry), file=file_like_obj)
                print(printer.format_entry(entry), file=file_like_obj)
                print(file=file_like_obj)
                
            # Thow an exception with the iostring as the message
            raise AssertionError("Entries are not the same. See the differences below:\n" + file_like_obj.getvalue())
    
    @loader.load_doc()
    def test_split_posting_percentage(self, entries, errors, options):
        """
        2020-01-01 open Assets:Cash
        2020-01-01 open Expenses:Food
        2020-01-01 open Expenses:Misc
        2020-01-01 open Expenses:Other
        
        2020-01-01 * "Buying something"
          Expenses:Food  100 USD
          Assets:Cash
        """

        for entry in entries:
            if not isinstance(entry, Transaction):
                continue
            for posting in entry.postings[:]:
                if posting.account == "Expenses:Food":
                    split_posting(entry,
                                  posting,
                                  (
                                    ("50%",   "Expenses:Misc"),
                                    ("_rest", "Expenses:Other")
                                    )
                                 )
                    
        printer.print_entries(entries)
        
        expected_ledger = textwrap.dedent("""
            2020-01-01 open Assets:Cash
            2020-01-01 open Expenses:Food
            2020-01-01 open Expenses:Misc
            2020-01-01 open Expenses:Other

            2020-01-01 * "Buying something"
                Expenses:Food    100 USD
                Expenses:Food   -100 USD
                Expenses:Misc   50.0 USD
                Expenses:Other  50.0 USD
                Assets:Cash     -100 USD
        """)
        
        entries_exp, _, _ = loader.load_string(expected_ledger)
        
        self.compare_entries(entries, entries_exp)

    @loader.load_doc()
    def test_split_posting_value(self, entries, errors, options):
        """
        2020-01-01 open Assets:Cash
        2020-01-01 open Expenses:Food
        2020-01-01 open Expenses:Misc
        2020-01-01 open Expenses:Other
        
        2020-01-01 * "Buying something"
          Expenses:Food  100 USD
          Assets:Cash
        """

        for entry in entries:
            if not isinstance(entry, Transaction):
                continue
            for posting in entry.postings[:]:
                if posting.account == "Expenses:Food":
                    split_posting(entry,
                                  posting,
                                  (
                                    ("50",   "Expenses:Misc"),
                                    ("_rest", "Expenses:Other")
                                    )
                                 )
                    
        printer.print_entries(entries)
        
        expected_ledger = textwrap.dedent("""
            2020-01-01 open Assets:Cash
            2020-01-01 open Expenses:Food
            2020-01-01 open Expenses:Misc
            2020-01-01 open Expenses:Other

            2020-01-01 * "Buying something"
                Expenses:Food    100 USD
                Expenses:Food   -100 USD
                Expenses:Misc     50 USD
                Expenses:Other    50 USD
                Assets:Cash     -100 USD
        """)
        
        entries_exp, _, _ = loader.load_string(expected_ledger)
        
        self.compare_entries(entries, entries_exp)

        
    @loader.load_doc()
    def test_split_posting_percentage_rest_wrong_place(self, entries, errors, options):
        """
        2020-01-01 open Assets:Cash
        2020-01-01 open Expenses:Food
        2020-01-01 open Expenses:Misc
        2020-01-01 open Expenses:Other
        
        2020-01-01 * "Buying something"
          Expenses:Food  100 USD
          Assets:Cash
        """

        for entry in entries:
            if not isinstance(entry, Transaction):
                continue
            for posting in entry.postings[:]:
                if posting.account == "Expenses:Food":
                    with self.assertRaises(ValueError):
                        split_posting(entry,
                                    posting,
                                    (
                                        ("_rest", "Expenses:Other"),
                                        ("50%",   "Expenses:Misc")
                                        )
                                    )
                    
        printer.print_entries(entries)
        
    @loader.load_doc()
    def test_split_posting_percentage_silent_remainder(self, entries, errors, options):
        """
        2020-01-01 open Assets:Cash
        2020-01-01 open Expenses:Food
        2020-01-01 open Expenses:Misc
        2020-01-01 open Expenses:Other
        
        2020-01-01 * "Buying something"
          Expenses:Food  100 USD
          Assets:Cash
        """

        for entry in entries:
            if not isinstance(entry, Transaction):
                continue
            for posting in entry.postings[:]:
                if posting.account == "Expenses:Food":
                    split_posting(entry,
                                  posting,
                                  (
                                    ("50%",   "Expenses:Misc"),
                                    )
                                 )
                    
        printer.print_entries(entries)
        
        expected_ledger = textwrap.dedent("""
                2020-01-01 open Assets:Cash
                2020-01-01 open Expenses:Food
                2020-01-01 open Expenses:Misc
                2020-01-01 open Expenses:Other

                2020-01-01 * "Buying something"
                    Expenses:Food   100 USD
                    Expenses:Food  -100 USD
                        posting_splitter: "reversed posting being split"
                    Expenses:Misc  50.0 USD
                        posting_splitter: "split from `Expenses:Food` based on the rule: `50%` `Expenses:Misc` "
                    Expenses:Food  50.0 USD
                        posting_splitter: "silent remainder from `Expenses:Food`"
                    Assets:Cash    -100 USD
        """)
        
        entries_exp, _, _ = loader.load_string(expected_ledger)
        
        self.compare_entries(entries, entries_exp)
        
        
    @loader.load_doc()
    def test_split_posting_percentage_with_price(self, entries, errors, options):
        """
        2020-01-01 open Assets:BankA
        2020-01-01 open Assets:BankB
        2020-01-01 open Assets:BankC
        
        2020-01-01 * "Exchange"
          Assets:BankA   100 USD @@ 50 EUR
          Assets:BankB  -50 EUR
        """

        for entry in entries:
            if not isinstance(entry, Transaction):
                continue
            for posting in entry.postings[:]:
                if posting.account == "Assets:BankA":
                    split_posting(entry,
                                  posting,
                                  (
                                    ("50%",   "Assets:BankB"),
                                    ("50%",   "Assets:BankC"),
                                    )
                                 )
                    
        printer.print_entries(entries)
        
        expected_ledger = textwrap.dedent("""
            2020-01-01 open Assets:BankA
            2020-01-01 open Assets:BankB
            2020-01-01 open Assets:BankC

            2020-01-01 * "Exchange"
                Assets:BankA   100 USD @ 0.5 EUR
                Assets:BankA  -100 USD @ 0.5 EUR
                    posting_splitter: "reversed posting being split"
                Assets:BankB  50.0 USD @ 0.5 EUR
                    posting_splitter: "split from `Assets:BankA` based on the rule: `50%` `Assets:BankB` "
                Assets:BankC  50.0 USD @ 0.5 EUR
                    posting_splitter: "split from `Assets:BankA` based on the rule: `50%` `Assets:BankC` "
                Assets:BankB   -50 EUR
        """)
        
        entries_exp, _, _ = loader.load_string(expected_ledger)
        
        self.compare_entries(entries, entries_exp)
        
        
    @loader.load_doc()
    def test_split_posting_value_wrong(self, entries, errors, options):
        """
        2020-01-01 open Assets:Cash
        2020-01-01 open Expenses:Food
        2020-01-01 open Expenses:Misc
        2020-01-01 open Expenses:Other
        
        2020-01-01 * "Buying something"
          Expenses:Food  100 USD
          Assets:Cash
        """

        with self.assertRaises(RuntimeError):
            for entry in entries:
                if not isinstance(entry, Transaction):
                    continue
                for posting in entry.postings[:]:
                    if posting.account == "Expenses:Food":    
                        split_posting(entry,
                                    posting,
                                    (
                                        ("120",   "Expenses:Misc"), # 120 is more than 100
                                        ("_rest", "Expenses:Other")
                                        )
                                    )
                    
    
if __name__ == '__main__':
    test_split_posting = Test_split_posting()
    
    test_split_posting.test_split_posting_value_wrong()