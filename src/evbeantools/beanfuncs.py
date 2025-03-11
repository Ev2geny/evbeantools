import copy
from collections import namedtuple
from typing import NamedTuple
from datetime import date
import io
import textwrap

from beancount.loader import load_file
from beancount.parser import printer
from beancount.parser import options
import beancount
from beancount.core.data import Transaction, Posting, Cost, Account
from beancount.parser import printer

from evbeantools.utils import check_convert_date

POSTING_SPLITTER_META = "posting_splitter"

def check_funds_in_transit(entries,
                           from_account: str,
                           in_transit_account: str,
                           to_account: str,
                           max_days_in_transit: int,
                           start_date: date | str | None = None,
                           end_date: date | str | None = None) -> list[NamedTuple]:
    """
    Checks whether funds sent from one account via transit account are received by another account within a specified number of days.
    This function is used to check for regular transfers from one account to another, where it takes a few days for the funds to be received.
    In such case one needs to send such funds via a transit account (e.g. Assets:Funds-In-Transit) in order not to break a balancing rule

    Args:
        entries (list): A list of entries to check.
        from_account (str): The account from which the funds are sent.
        in_transit_account (str): The account through which the funds are in transit.
        to_account (str): The account to which the funds are supposed to be received.
        max_days_in_transit (int): The maximum number of days the funds are allowed to be in transit.
        start_date (date|str|None, optional): The start date from which to check the entries. Defaults to None.
        end_date (date|str|None, optional): The end date until which to check the entries. Defaults to None.

    Returns:
        list[NamedTuple]: A list of NamedTuples each representing an error where funds were not received within the specified number of days. Each NamedTuple contains the source, an error message, and the entry associated with the error.

    Raises:
        Exception: If there is an error in retrieving or processing the data.
    """    
    
    if start_date:
        start_date=check_convert_date(start_date)
    
    if end_date:
        end_date=check_convert_date(end_date)
    
    # Looping through all entries
    
    from_postings=[]
    to_postings=[]
    
    # Builting lists of from_postings and to_postings
    
    
    for entry in entries:
        
        # checking that entry is a transaction
        if not isinstance(entry, beancount.core.data.Transaction):
            continue
        
        # Checking if the entry has postings
        
        if start_date and entry.date < start_date:
            continue
        
        if end_date and entry.date > end_date:
            continue
        
        if entry.postings:
            # Looping through all postings in the entry
            for posting in entry.postings:
                # Checking if the posting has an account from_account
                if posting.account == from_account:
                    # print(posting.account)
                    for other_posting in entry.postings:
                        # print(other_posting.account)
                        if other_posting.account == in_transit_account and \
                            other_posting.units.currency == posting.units.currency and \
                            other_posting.units.number == (-1)*posting.units.number:
                                from_postings.append((posting, entry))
                
                if posting.account == to_account:
                    for other_posting in entry.postings:
                        if other_posting.account == in_transit_account and \
                            other_posting.units.currency == posting.units.currency and \
                            other_posting.units.number == (-1)*posting.units.number:
                                to_postings.append((posting, entry))
    
    # print('***********   from_postings   ***********')  
                            
    # for posting in from_postings:
    #     print(posting)          
    
    # print('***********   to_postings   ***********')
    # for posting in to_postings:
    #     print(posting)
        
    errors = []
    FundsLostInTransitError = namedtuple('FundsLostInTransitError', ['source', 'message','entry'])
    
    
    for from_posting in from_postings:
        for i, to_posting in enumerate(to_postings):
            if (from_posting[1].date > to_posting[1].date) or (to_posting[1].date - from_posting[1].date ).days > max_days_in_transit:
                continue
            
            if from_posting[0].units.currency == to_posting[0].units.currency and from_posting[0].units.number == to_posting[0].units.number * (-1):
                # removing element i from to_postings
                del to_postings[i]
                break
        else:
            # if there is no break in the loop
            error_message = f"Funds were sent via the below path but were not received within {max_days_in_transit} days\n\n'{from_account}' ==> '{in_transit_account}' ==> '{to_account}'\n"
            error_entry = from_posting[1]
            meta= from_posting[1].meta
            error_object=FundsLostInTransitError(meta, error_message, error_entry)
            errors.append(error_object)
            
    # Checking if there are any funds received by to_account, but not sent from from_account
    # If all transactions were matched, then to_postings should be empty, as we were removing matched transactions from to_postings        
    for to_posting in to_postings:
        error_message = f"Some funds were received via the path\n\n '{from_account}' ==> '{in_transit_account}' ==> '{to_account}'\n\n but were not sent during the perevious {max_days_in_transit} days"
        
        error_entry = to_posting[1]
        meta= to_posting[1].meta
        error_object=FundsLostInTransitError(meta, error_message, error_entry)
        errors.append(error_object)

    errors.sort(key=lambda x: x.entry.date)
    
    return errors

def check_mult_funds_in_transit(entries: list,
                                params: list[list | tuple] | tuple[list | tuple]) -> list[NamedTuple]:
    """The same as check_funds_in_transit, but takes a list or tuple of parameters instead of individual parameters

    Args:
        entries: A list of entries to check.
        params : A list of lists or tuples each containing parameters for check_funds_in_transit function
            from_account (str): The account from which the funds are sent.
            in_transit_account (str): The account through which the funds are in transit. E.g. Assets:Funds-In-Transit 
            to_account (str): The account to which the funds are supposed to be received.
            max_days_in_transit (int): The maximum number of days the funds are allowed to be in transit.
            start_date (date|str|None, optional): The start date from which to check the entries. Defaults to None.
            end_date (date|str|None, optional): The end date until which to check the entries. Defaults to None.

    Returns:
        list[NamedTuple]: A list of NamedTuples each representing an error where funds were not received within the 
                        specified number of days. Each NamedTuple contains the source, an error message, and the entry associated with the error.

    Raises:
        Exception: If there is an error in retrieving or processing the data.
    """
    
    if not isinstance(params, (tuple,list)):
        raise ValueError(f"Paramater params shall be either tuple or list, but it is {type(params)}")
        
    
    errors=[]
    for param in params:
        errors.extend(check_funds_in_transit(entries, *param))
    
    return errors
        
        
from decimal import Decimal
from beancount.core.data import Transaction, Posting, Amount, Account


def split_posting(transaction: Transaction,
                  posting: Posting,
                  splitting_info: tuple[tuple[str, Account]]):
    """
    Splits a posting in transaction into multiple postings based on the splitting_info provided.

    Args:
        transaction (Transaction): The transaction to split.
        posting (Posting): The posting to split.
        splitting_info (tuple[tuple[str, Account]]): A tuple of tuples, containing information on how
            to split the posting. Each inner tuple should be of the form:
                (split_amount_str, account),
            where:
                - split_amount_str (str) can be:
                    - '[number]%': e.g. '50%', representing a percentage of the original posting's amount.
                    - '[number]': e.g. '12.90', a fixed amount (will be parsed with Decimal).
                    - '_rest': Special keyword indicating "the remaining balance".
                - account (Account): The beancount account to which the split portion will be posted.

    Returns:
        None: The transaction is modified in place (the original posting is removed,
              and new postings are appended to transaction.postings).
    """
    
    def check_remainder_sign_did_not_change(original_amount, remainder_amount):
        """
        Checks that the remainder amount has the same sign as the original amount.
        If the sign has changed, raises a RuntimeError.
        """
        
        if original_amount * remainder_amount > Decimal("0"):
            return 

        transation_str = printer.format_entry(transaction)
        
        error_str = f"""
        Error occured while splitting the posting in the transaction:
        
        {transation_str}
        
        By using the following splitting_info:
        
        {splitting_info}
        
        Total split amount exceeds the original amount by {remainder_amount}
        """
        transation_str = textwrap.dedent(transation_str)
        
        raise RuntimeError(error_str)
    
        
    
    
    posting_index = transaction.postings.index(posting)
    

    original_amount = posting.units.number  # The numeric portion (Decimal) of the original posting
    currency = posting.units.currency       # The currency of the original posting

    # We will accumulate how much has been split so far
    allocated_amount = Decimal("0")

    # Collect the newly created postings here
    new_postings = []

    # creating a new posting, equivalent to the original posting, but with the opposite sign
    
    reversed_units = Amount(-posting.units.number, posting.units.currency)
    
    reversed_posting = Posting(
        account=posting.account,
        units=reversed_units,
        cost=posting.cost,
        price=posting.price,
        flag=posting.flag,
        meta=copy.copy(posting.meta) or {}
    )
    
    reversed_posting.meta[POSTING_SPLITTER_META] = "reversed posting being split"
    
    new_postings.append(reversed_posting)

    rest_found_flag = False

    # Parse the split instructions
    for index, (split_str, split_account) in enumerate(splitting_info):
        if split_str == "_rest":
            # Whatever is left from the original amount
            if index != len(splitting_info) - 1:
                raise ValueError("The '_rest' keyword must be used only in the last split.")
            
            split_value = original_amount - allocated_amount
            
            check_remainder_sign_did_not_change(original_amount, split_value)
                
            
            rest_found_flag = True
            
        elif split_str.endswith("%"):
            # Split by percentage
            percentage = Decimal(split_str[:-1]) / Decimal("100")
            split_value = original_amount * percentage
        else:
            # Fixed decimal amount
            split_value = Decimal(split_str)

        allocated_amount += split_value

        # Create a new posting with the split portion
        
        new_posting = Posting(
            account=split_account,
            units=Amount(split_value, currency),
            cost=posting.cost,
            price=posting.price,
            flag=posting.flag,
            meta=copy.copy(posting.meta) or {}
        )
        
        new_posting.meta[POSTING_SPLITTER_META] = f"split from `{posting.account}` based on the rule: `{split_str}` `{split_account}` "
        
        new_postings.append(new_posting)
        
    if not rest_found_flag and allocated_amount != original_amount:
        silent_remainder = original_amount - allocated_amount
        new_posting = Posting(
            account=posting.account,
            units=Amount(silent_remainder, currency),
            cost=posting.cost,
            price=posting.price,
            flag=posting.flag,
            meta=copy.copy(posting.meta) or {}
        )
        
        check_remainder_sign_did_not_change(original_amount, silent_remainder)
        
        new_posting.meta[POSTING_SPLITTER_META] = f"silent remainder from `{posting.account}`"
        
        new_postings.append(new_posting)


    # Remove the original posting from the transaction
    # transaction.postings.remove(posting)

    # Inserrting the new postings straight after the original posting
    transaction.postings[posting_index+1:posting_index+1] = new_postings
    


