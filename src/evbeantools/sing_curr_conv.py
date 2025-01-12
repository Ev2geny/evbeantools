import builtins
from pprint import pprint
import logging
import datetime
import decimal
from decimal import Decimal
from collections import OrderedDict, defaultdict
import logging
from pprint import pprint, pformat
import tempfile
import textwrap
from pathlib import Path
import ast
import argparse
import io
from typing import NamedTuple
import os
import copy

from beanquery.query import run_query
import beanquery



from beancount.core.inventory import Inventory
from beancount.core import data
from beancount.core import interpolate
from beancount.core.data import Open, Close, Commodity, Transaction, Balance, Pad, Note, Document, Price, Event, Query, Custom
from beancount.core.data import Account, Currency
from beancount.core import account
from beancount.core import convert
from beancount.core import prices
from beancount.core.prices import get_price, get_all_prices
from beancount.core.number import D
from beancount.core.amount import Amount
from beancount.parser import printer
from beancount import loader
from beancount.plugins.auto_accounts import auto_insert_open

import beanquery.shell

# from pydantic import ValidationError, validate_call

from evbeantools.summator import BeanSummator, InventoryAggregator
from evbeantools.sing_curr_conv_utils import check_vs_beanquery

# This is to make sure, that the module can be run as beancount plugin
__plugins__ = ['get_equiv_sing_curr_entries_pulugin']

logger = logging.getLogger()

TOLERANCE_DEF = "0.009"

SINGLE_CURENCY_CONVERTER_MSG_META = 'scc_msg'
SINGLE_CURENCY_CONVERTER_NAME = 'Single Currency Converter'
TRACKED_AT_COST_META_NAME = 'scc_at_cost'
TRACKED_AT_COST_META_MSG = 'at_cost'
TRACKED_NOT_AT_COST_META_MSG = 'no_cost'

UNREALIZED_GAINS_CAUSE_META_NAME = 'scc_unreal_g_cause'
UNREALIZED_GAINS_BAL_S_ACC_META_NAME = 'scc_bal_s_acc'

UNREAL_GAINES_P_AND_L_ACC: Account = "Income:Unrealized-Gains"

#This is the account, which is used to record gains and losses, which are caused by the difference in the price used to 
# weight the posting and the price in the price map, which is used to convert the transaction to single currency
# E.g.
"""
2020-01-01 price USD 1 EUR

2020-01-02 * "Exchange 100 USD to EUR"
    Assets:USD  -200 USD
    Assets:EUR   100 EUR @ 2 USD ; Here the price is 2 USD, not 1 EUR as in price directive
"""
# Current understanding is that it must be equal to the account UNREAL_GAINES_P_AND_L_ACC
ACC_FOR_PRICE_DIFF: Account = UNREAL_GAINES_P_AND_L_ACC

GAINS_SUFFIX = ""


def print_entries_to_string(entries) -> str:
    """
    Helper function, which prints entries to string
    Used for testing and debugging   

    Args:
        entries (_type_): _description_

    Returns:
        str: lenger file in text format
    """
    file_replacement = io.StringIO()
    printer.print_entries(entries, file=file_replacement)
    entries_str = file_replacement.getvalue()
    file_replacement.close()
    return entries_str    


def print_errors_to_string(errors):
    """
    Helper function, which prints errorrs to string
    Used for testing and debugging   

    Args:
        entries (_type_): _description_

    Returns:
        str: lenger file in text format
    """
    file_replacement = io.StringIO()
    printer.print_errors(errors, file=file_replacement)
    errors_str = file_replacement.getvalue()
    file_replacement.close()
    return errors_str    


# This is just a type desclartion for type hints
Commodities = set[Currency]

# Dictionary, which maps currency to the date, when the currency was first used in any transaction in the ledger
CurrencyIntroductionMap = dict[Currency, datetime.date]

def get_currency_units_at_cost_and_no_cost(inventory: Inventory, currency) -> tuple[Amount, Amount]:
    """
    Identical to the beancount Inventory.get_currency_units(currency), but returns a tuple with 2 values:
        1. Amount of units of currency, which were tracked at cost
        2. Amount of units of currency, which were not tracked at cost

    In most of the cases the same currency will be tracked either at cost or not at cost, 
    but this handles the rare case, when the same commodity is tracked at cost in the same inventory

    Args:
        inventory (Inventory): _description_

    Returns:
        tuple[Amount, Amount]: _description_
    """
    
    
    
    total_units_at_cost = decimal.Decimal()
    total_units_at_no_cost = decimal.Decimal()
    
    for position in inventory:
        if position.units.currency == currency:
            if position.cost is not None:
                total_units_at_cost += position.units.number
            else:
                total_units_at_no_cost += position.units.number
    
    return Amount(total_units_at_cost, currency), Amount(total_units_at_no_cost, currency)
      


def build_currency_introduction_map(entries) -> CurrencyIntroductionMap:
    
    result = dict()
    
    for entry in entries:
        if isinstance(entry, Transaction):
            for posting in entry.postings:
                currency = posting.units.currency
                if not result.get(currency) or result[currency] > entry.date:
                    result[currency] = entry.date
    
    return result

def get_fist_date_of_price(price_map, base_quote) -> datetime.date | None:
    """
    Returns the first date, when the price between currency_a and currency_b was introduced in the ledger

    Args:
        price_map (_type_): _description_
        base_quote: A pair of strings, the base currency to lookup, and the quote
            currency to lookup, which expresses which units the base currency is
            denominated in. This may also just be a string, with a '/' separator.

    Returns:
        datetime.date|None: _description_
    """
    
    try:
        all_prices = get_all_prices(price_map, base_quote)
    except KeyError:
        return None
    
    return all_prices[0][0]


def filter_out_commodities_from_inventory(inventory: Inventory, commodities: Commodities) -> Inventory:
    """
    Returns a new inventory, which is the same as the input inventory, but only with all positions in commodities which 
    are NOT in the commodities set

    Args:
        inventory (Inventory): original inventory
        commodities (Commodities): set of commodities, which should be filtered out

    Returns:
        Inventory: a new inventory
    """
    
    result = Inventory()
    
    for position in inventory:
        if position.units.currency not in commodities:
            result.add_position(position)
    
    return result


def create_equivalent_starting_transaction(net_worth_calculator: BeanSummator,
                                           options,
                                           date: datetime.date,
                                           currency: Currency,
                                           price_map) -> tuple[Transaction | None, Commodities | None]:
    """
    Creates transaction, which is equivalent to balsheet status on the previous date
    Such transaction effectively replaces all previous transactions, which were used to calculate balsheet status
    One posting of this transaction goes to Equity:OpeningBalances account, and the other postings are to all 
    balsheet accounts
    
    Returns:
        Tuple with 2 values
            Equivalent transaction, which is equivalent to balsheet status on the previous date or None, 
                if balsheet status is empty (may happen, if there are no transactions before the date)
            
            UnconvertableCommodities: A set of commodities, which are unconvertable to the target currency
    
    """
    
    EQUIVALENT_OPENING_BALANCES_ACC = "Equity:OpeningBalances"
    
    unconvertable_commodities = set()
    
    previous_date = date - datetime.timedelta(days=1)

    bal_sheet_rows_multicurr: InventoryAggregator = net_worth_calculator.sum_till_date(previous_date).clean_empty()
    
    if bal_sheet_rows_multicurr.is_empty():
        return None, None
    
    bal_sheet_rows_single_curr = bal_sheet_rows_multicurr.convert(currency, price_map, previous_date)

    total_neth_worth_inventory = bal_sheet_rows_single_curr.sum_all()
    
    # total_net_worth_units = total_neth_worth_inventory.get_only_position().units
    
    narration = "Opening balance single currency transaction, equivalent to the Balance Sheet status on that date"
    
    meta ={}
    # The lineno meta is needed to make sure, the code of plugings which gets used afterwards works without errors
    meta["lineno"] = 0
    meta[SINGLE_CURENCY_CONVERTER_MSG_META] = f"Created by the {SINGLE_CURENCY_CONVERTER_NAME}"
    
    transaction = data.Transaction(meta=meta, 
                                   flag="*", 
                                   date=previous_date, 
                                   payee="", 
                                   narration=narration,
                                   tags=data.EMPTY_SET,
                                   links=data.EMPTY_SET,
                                   postings=[])
    
    for position in total_neth_worth_inventory:
        
        if position.units.currency != currency:
            unconvertable_commodities.add(position.units.currency)
    
        equity_posting = data.Posting(account=EQUIVALENT_OPENING_BALANCES_ACC,
                                    units=-position.units,
                                    cost=None,
                                    price=None,
                                    flag=None,
                                    meta=None)
        
        transaction.postings.append(equity_posting)
    
    # Creating postings for all balsheet accounts
    for account, converted_inventory in bal_sheet_rows_single_curr.items():
        
        # The below loop will have more than 1 iteration only in case there are unconvertable commodities in the position
        for position in converted_inventory:
            position_currency = position.units.currency
            
            # Finding out the original balance in the original currency 
            if position_currency != currency:
                # Dealing with the case, when the commodity is unconvertable
                assert position_currency in unconvertable_commodities, f"Internal error: position_currency not in unconvertable_commodities: {position_currency} not in {unconvertable_commodities}"
                original_balance = bal_sheet_rows_multicurr[account].get_currency_units(position_currency)
            else:
                original_balance = filter_out_commodities_from_inventory(bal_sheet_rows_multicurr[account], unconvertable_commodities)
            
            bal_sheet_posting_meta = {f"{SINGLE_CURENCY_CONVERTER_MSG_META}": f"Balance in original currency {original_balance}"}
            bal_sheet_account_posting = data.Posting(account=account,
                                                    units=position.units,
                                                    cost=None,
                                                    price=None,
                                                    flag=None,
                                                    meta=bal_sheet_posting_meta)
            transaction.postings.append(bal_sheet_account_posting)
          
    return transaction, unconvertable_commodities


def create_unrealized_gains_transaction(net_worth_diff: InventoryAggregator,
                                        date: str,
                                        currency_changed: str,
                                        old_price,
                                        new_price,
                                        target_currency: str,
                                        options: dict,
                                        net_worth_on_date_multicurr: InventoryAggregator,
                                        unreal_gains_p_l_acc: str,
                                        group_p_l_acc_tr: bool = False) -> Transaction | None:
    """
    Returns a transaction, which represents unrealized gains, which are caused by the change in the price of the currency
    vs the target currency.

    Args:
        net_worth_diff: an InventoryAggregator, which contains the difference in the net worth, expressed in the target 
             currency, which now needs to be converted to an unrealized gains transaction.
             This inventory aggregator will contain mostly 1 position for each account, expressed in the target currency
             If the original currency/commodity, which has caused this net_worth_diff was tracked at cost, then the 
             position will contain a dummy cost: 1 REMOVEDCOST. E.g. 
             
             InventoryAggregator({'Assets:Bank1': "100.0 USD {1 REMOVEDCOST}"})
             
             This 1 REMOVEDCOST is used to indicate, that the position was tracked at cost. This is later used to provide
             Information in the meta of the unrealized gains postings. This is to allow one later to sepate the unrealized
             gains, for things, which were tracked at cost and for things, which were not tracked at cost (e.g. for tax purposes)
             
             There is a reare, but still theoretically possible case, when the inventory will have 2 positions for the 
             same account. This would be the case when the same commodity was tracked at cost at some transactions and 
             not tracked at cost at other transactions. See below in teh body of the function for more details in the comments
        
        date: 
        
        currency_changed: The currency, which price has changed in relation to the target currency
        
        old_price:  old price of the currency_changed, expressed in the target currency
        
        new_price:  new price of the currency_changed, expressed in the target currency
        
        target_currency: The target single currency, to which all transactions are being converted
        
        net_worth_on_date_multicurr:  InventoryAggregator, which contains the Net worth on the date in multicurrency 
                          (not converted yet to single currency). Used here only to put currect message in the meta 
        
        unreal_gains_p_l_acc: and account, which will be used to record unrealized gains.  
        
        group_p_l_acc_tr: If True, then all unrealized gains, caused by value change of diffenet bal sheet accounts 
                          will be grouped into a single posting. 
                          This creates more compact unrealized gains transactions, but in this case the transaction meta
                          'scc_bal_s_acc' is not added to this posting
                          

    Returns:
        Transaction|None: _description_
    """
    
    # logging.error(f"Creating unrealized gains transaction for date {date}")
    
    logger.debug(f"Creating unrealized gains transaction for date {date} \n net_worth_diff = {pformat(net_worth_diff)}")
    
    narration = f"Unrealized gains due to {currency_changed} price change from {old_price} to {new_price} {target_currency} ({target_currency} price change from {1/old_price} to {1/new_price} {currency_changed})"
    
    group_p_l_acc_meta = {f"{SINGLE_CURENCY_CONVERTER_MSG_META}": f"Created by the {SINGLE_CURENCY_CONVERTER_NAME}"}
     # The lineno meta is needed to make sure, the code of plugings which gets used afterwards works without errors
    group_p_l_acc_meta["lineno"] = 0
    
    flag = "*"
    payee = ""
    transaction = data.Transaction(meta=group_p_l_acc_meta,
                                   flag=flag,
                                    date=date,
                                    payee=payee,
                                    narration=narration,
                                    tags=data.EMPTY_SET,
                                    links=data.EMPTY_SET,
                                    postings=[])
    
    # this will hold an inventory, which is equivant to change in P&L account
    p_and_l_account_total_invent = Inventory()
    
     # creating a name for P&L account    
    unreal_gains_p_l_acc = f"{unreal_gains_p_l_acc}:{target_currency}-{currency_changed}{GAINS_SUFFIX}"	
        
    for account, inventory in net_worth_diff.items():
        
        if len(inventory) > 2:
            raise RuntimeError(f"Internal error: inventory has more than 2 positions: {pformat(inventory)}. Max. 2 were expected. One with cost and one without")

        # We need the below loop for very rare cases, which will probably never happen, but still seems to be possible in beancount
        # Namely, when there are 2 positions for the same commщdity at the same account, but one is tracked at cost 
        # and the other is not. 
        # Originally this would have bann caused by the situation like this:
        """
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking   -200 USD
            Assets:Investments     2 IVV {100 USD}
            
        2020-01-03 * "Buying at cost"
            Assets:Bank:Checking  -200 USD
            Assets:Investments    2 IVV @ 100 USD
        """
        # At this point however such situation will be represented by the fact, that net_worth_diff will have 2 
        # positions at the same account:
        # net_worth_diff == {'Assets:Investments': (200 USD, 200 USD {1 REMOVEDCOST})}
        
        for position in inventory:
            
            p_and_l_account_total_invent.add_position(position)
            
            # logger.debug(f"p_and_l_account_total_invent after addition: {pformat(p_and_l_account_total_invent)}")
            
            final_bal_sheet_account = account
        
            tracked_at_cost_meta_msg = None
            
            original_currency_balance: tuple = get_currency_units_at_cost_and_no_cost(net_worth_on_date_multicurr[account], currency_changed)
            
            if position.cost is not None:
                tracked_at_cost_meta_msg = TRACKED_AT_COST_META_MSG
                
                # at the 1st position in the tuple is the amount of units of given currency, which were tracked at cost
                original_currency_balance = original_currency_balance[0]
            else:
                tracked_at_cost_meta_msg = TRACKED_NOT_AT_COST_META_MSG
                
                # at the 2nd position in the tuple is the amount of units of given currency, which were tracked at no cost
                original_currency_balance = original_currency_balance[1]
                
            
            bal_sheet_acc_meta = {f"{SINGLE_CURENCY_CONVERTER_MSG_META}": f"Calculated on the balance of {original_currency_balance} at the beginning of this day (end of prev. day)",
                                TRACKED_AT_COST_META_NAME: tracked_at_cost_meta_msg,
                                UNREALIZED_GAINS_CAUSE_META_NAME: "price_change"}
            
            bal_sheet_posting = data.Posting(account=final_bal_sheet_account,
                                            units=position.units,
                                            cost=None,
                                            price=None,
                                            flag=None,
                                            meta=bal_sheet_acc_meta)
            
            transaction.postings.append(bal_sheet_posting)
            
            
            if not group_p_l_acc_tr:
                
                #The not groupped P&L account posting  shall contain the same meta as the bal_sheet_posting  
                p_and_l_meta = bal_sheet_acc_meta.copy()
                p_and_l_meta[UNREALIZED_GAINS_BAL_S_ACC_META_NAME] = final_bal_sheet_account
                
                p_and_l_posting = data.Posting(account=unreal_gains_p_l_acc,
                                            units=-position.units,
                                            cost=None,
                                            price=None,
                                            flag=None,
                                            meta=p_and_l_meta)
                
                transaction.postings.append(p_and_l_posting)
        

    if group_p_l_acc_tr and not p_and_l_account_total_invent.is_empty():
        
        logger.debug(f"Adding to p_and_l_account_total_invent: {pformat(p_and_l_account_total_invent)}")
        
        for position in p_and_l_account_total_invent:
            
            tracked_at_cost_meta_msg = TRACKED_NOT_AT_COST_META_MSG
            
            if position.cost is not None:
                tracked_at_cost_meta_msg = TRACKED_AT_COST_META_MSG
        
            group_p_l_acc_meta = {TRACKED_AT_COST_META_NAME: tracked_at_cost_meta_msg,
                    UNREALIZED_GAINS_CAUSE_META_NAME: "price_change"}
        
            p_and_l_combined_posting  = data.Posting(account=unreal_gains_p_l_acc,
                                units=-position.units,
                                cost=None,
                                price=None,
                                flag=None,
                                meta=group_p_l_acc_meta)
            
            transaction.postings.insert(0, p_and_l_combined_posting)
        
    if len(transaction.postings) == 0:
        return None
        
    account_for_error_correction = f"{unreal_gains_p_l_acc}:{target_currency}-{target_currency}"
    transaction = add_balance_error_correction_posting_if_needed(transaction, 
                                                                 options, 
                                                                 account_for_error_correction)    
        
    return transaction


class SingleCurrencyConversionErr(Exception):
    pass

class ConversionRateNotFoundErr(SingleCurrencyConversionErr):
    pass

class TransferFundsToFromUnconvertableCommErr(SingleCurrencyConversionErr):
    pass

class UnconvertableCommBecomesConvertibleErr(SingleCurrencyConversionErr):
    pass


def convert_amount(original_unit: Amount,
                     target_currency: Currency,
                     price_map, 
                     date: datetime.date) -> Amount:
    """
    Convert a Beancount unit to a different currency.

    Args:
        original_unit (beancount.core.amount.Amount): The original unit to convert.
        target_currency (str): The currency to convert to.
        price_map (dict): A dictionary mapping (currency, date) pairs to conversion rates.
        date (datetime.date): The date at which the conversion rate should be derived.
        
    Raises:
        ConversionRateNotFoundErr: If the conversion rate is not found in the price_map

    Returns:
    beancount.core.amount.Amount: The converted amount in the target currency.
    """
    if not isinstance(original_unit, Amount):
        raise ValueError("original_unit must be a beancount.core.amount.Amount instance")

    # Get the conversion rate for the original unit's currency on the given date
    _, conversion_rate = prices.get_price(price_map, original_unit.currency +"/"+ target_currency, date)

    if conversion_rate is None:
        raise ConversionRateNotFoundErr(f"No conversion rate found for currency {original_unit.currency} on date {date}")

    converted_number = D(original_unit.number) * conversion_rate
    return Amount(converted_number, target_currency)

def add_balance_error_correction_posting_if_needed(transaction: Transaction, options, account: Account) -> Transaction:
    """
    This function is a workaround for the issue_11.
    Sometimes converted transactions do not balance with the very small error, probably due to the imperfection of the 
    beancount. This function check whether the transactions is balanced and if not, it adds a posting to compensate the 
    error
    
    The below code is based on the beancount function beancount.ops.validate_check_transaction_balances, therefore
    it is assumes, thet the same mechanism is used to calculate the residual as in the beancount itself
    
    Args:
        transaction (Transaction): The transaction to check
        options (dict): The options dictionary
        account (Account): The account to which the correction posting should be added
    
    Returns:
        Transaction: The transaction with the correction posting added if needed
    """
    # TODO: @Ev2geny: Check if the below threshold is good enough, now it is just a guess
    THRESHOLD = 0.0001
    
    residual = interpolate.compute_residual(transaction.postings)
    tolerances = interpolate.infer_tolerances(transaction.postings, options)
    
    if residual.is_small(tolerances):
        return transaction
    
    residual_error_number = residual.get_only_position().units.number
    
    # We really want such correction to happen only in the case of very small values, otherwise there must be something 
    # wrong
    if abs(residual_error_number) > THRESHOLD:
        raise RuntimeError(f"Internal error: error for balance correction is above the threshold ({THRESHOLD}): {residual_error_number}")
    
    meta = {}
    
    meta[SINGLE_CURENCY_CONVERTER_MSG_META] = f"Balance error correction posting"
    
    correction_posting = data.Posting(account=account,
                                      units=-residual.get_only_position().units,
                                      cost=None,
                                      price=None,
                                      flag=None,
                                      meta=meta)
    
    transaction.postings.append(correction_posting)
    
    return transaction
    

def convert_transaction_to_new_currency(original_transaction: Transaction,
                                        target_currency: Currency,
                                        price_map,
                                        currency_introduction_map: CurrencyIntroductionMap,
                                        unconvertable_commodities: Commodities,
                                        account_for_price_diff: Account,
                                        options: dict) -> tuple[Transaction, Commodities]:
    """
    Attempts to convert all units in a transaction to a new currency.

    Args:
        original_transaction: The original transaction to convert.
        target_currency The currency to convert to.
        price_map: A dictionary mapping (currency, date) pairs to conversion rates.
        unconvertable_commodities: A set of commodities, which are unconvertable
        account_for_price_diff

    Returns:
        beancount.core.data.Transaction: The converted transaction.
    """
    
    original_transaction = copy.deepcopy(original_transaction)
    
    unconvertable_commodities_to_return: Commodities = unconvertable_commodities.copy()
    
    converted_transaction = data.Transaction(meta=original_transaction.meta, 
                                             flag=original_transaction.flag, 
                                             date=original_transaction.date, 
                                             payee=original_transaction.payee, 
                                             narration=original_transaction.narration,
                                             tags=original_transaction.tags,
                                             links=original_transaction.links,
                                             postings=[])

    logger.debug(f"Converting transaction:\n {pformat(original_transaction)}")
    
    at_least_one_posting_converted = False
    for original_posting in original_transaction.postings:
        
        # logger.debug(f"Converting posting:\n {pformat(original_posting)}")
        
        new_units = None

        new_meta = original_posting.meta if original_posting.meta else {}
        
        first_date_of_price = get_fist_date_of_price(price_map, (original_posting.units.currency, target_currency))
    
        # The most simple case, when the posting is already in the target currency and has no cost or price
        if original_posting.units.currency == target_currency and \
            original_posting.cost is None and original_posting.price is None:
            new_posting = original_posting
        
        else:
            
            at_least_one_posting_converted = True
            
            # In this case we just only effectively remove cost and price, no conversion is needed
            if original_posting.units.currency == target_currency:
                new_units = original_posting.units
                new_meta[SINGLE_CURENCY_CONVERTER_MSG_META] = f"Converted from original posting in the same currency by removing cost and/or price"
            else:
                
                if (original_posting.units.currency in unconvertable_commodities_to_return) and \
                (original_posting.cost is not None or original_posting.price is not None):
                    
                    
                    # TODO: @Ev2geny: Check why in the error message the original transaction is being printed with the 
                    # metadata as if it is a converted transaction
                    
                    #TODO: @Ev2geny: Add more information on how to fix the problem
                    
                    error_message = None
                    if first_date_of_price:
                        error_message = f"""
                        Problem with provided beancount ledger has been detected while converting, which does not allow to perform correct 
                        conversion of entries to a single currency {target_currency}.
                        Commodity {original_posting.units.currency} has been detected as unconvertable in the past transactions. 
                        However on the date {original_transaction.date} funds are being transferred to/from this commodity and the other commodity. 
                        
                        Affected transaction:\n{printer.format_entry(original_transaction)}
                        
                        Affected posting in the affected transaction:\n{original_posting}
                        
                        To fix the problem do one of the following: 
                        - make sure, that the conversion is requested with the start date on of after the date the price for conversion of  {original_posting.units.currency} to {target_currency} was 1st introduced ({first_date_of_price})
                        - make sure, that there is a price entry for  conversion of  {original_posting.units.currency} to {target_currency} on or before the commodity  {original_posting.units.currency} was 1st used in a transaction ({currency_introduction_map.get(original_posting.units.currency)})
                        """
                        
                    else:
                        error_message = f"""
                        Problem with provided beancount ledger has been detected while converting, which does not allow to perform correct 
                        conversion of entries to a single currency {target_currency}.
                        Commodity {original_posting.units.currency} is unconvertable to {target_currency}.
                         
                        However on the date {original_transaction.date} funds are being transferred to/from this commodity and the other commodity. 
                        
                        Affected transaction:\n{printer.format_entry(original_transaction)}
                        
                        Affected posting in the affected transaction:\n{original_posting}
                        
                        One of the ways to fix the problem is to make sure there is a price entry for  conversion of  {original_posting.units.currency} to {target_currency} on or before the commodity  {original_posting.units.currency} was 1st used in a transaction ({currency_introduction_map.get(original_posting.units.currency)})
                        """
                        
                    error_message = textwrap.dedent(error_message)
                    
                    
                    raise TransferFundsToFromUnconvertableCommErr(f"\n {error_message}")
                
                try:
                    new_units = convert_amount(original_posting.units, target_currency, price_map, original_transaction.date)
                    new_meta[SINGLE_CURENCY_CONVERTER_MSG_META] = f"Converted from {original_posting.units.number} {original_posting.units.currency}"
                    
                except ConversionRateNotFoundErr as error:
                    
                    # Checking if original posting has cost or price, we cannot proceed
                    if original_posting.cost is not None or original_posting.price is not None:
                        error_message = f"""
                        Problem with provided beancount ledger has been detected while converting, which does not allow to perform correct 
                        conversion of entries to a single currency {target_currency}.
                        Commodity {original_posting.units.currency} is unconvertable to the {target_currency} on the date {original_transaction.date}.
                        This means, that until including the date {original_transaction.date} there is no price entry for conversion of {original_posting.units.currency} to {target_currency}. 
                        
                        However on the date {original_transaction.date} funds are being transferred to/from this commodity and the other commodity. 
                        
                        Affected transaction:\n{printer.format_entry(original_transaction)}
                        
                        Affected posting in the affected transaction:\n{original_posting}
                        
                        To fix the problem do one of the following: 
                            - make sure, that the conversion is requested with the start date on of after the date the price for conversion of {original_posting.units.currency} to {target_currency} was 1st introduced ({first_date_of_price})
                            - make sure, that there is a price entry for  conversion of  {original_posting.units.currency} to {target_currency} on or before {original_transaction.date}
                        """
                        error_message = textwrap.dedent(error_message)
                        
                        # TODO: remove
                        # error_message = "Updated error message"
                    
                        raise TransferFundsToFromUnconvertableCommErr(f"\n {error_message}")
                    
                    
                    # Otherwise we are just adding the posting as is, without conversion and declare this commodity as unconvertable    
                    new_units = original_posting.units
                    unconvertable_commodities_to_return = unconvertable_commodities_to_return|{original_posting.units.currency}
                                          
            new_posting = data.Posting(account=original_posting.account,
                                       units=new_units,
                                       cost=None,
                                       # price=original_posting.price,
                                       price=None,
                                       flag=original_posting.flag,
                                       meta=new_meta)
                 
            
        converted_transaction.postings.append(new_posting)
        
        if original_posting.cost is None and original_posting.price is None:
            continue
        
        
        # Now we need to check if a "hidden gain" posting is needed
        # Price correction posting is a posting, which may have to be added if posting involves conversion from one 
        # currency to another at a price, different from the one specified by the price directive 

        # Examples:     
        #      2020-01-01 price HOO 10 USD
        #      2020-01-01 * "Buying some HOO"
        #          Assets:Bank:Checking  
        #          Assets:Investments  10 HOO @ 15 USD; <== Here the price is 15 USD, not 10 USD as in price directive
        # or   
        #    2020-01-01 price HOO 10 USD
        #    2020-01-01 * "Buying some HOO"
        #        Assets:Bank:Checking  
        #        Assets:Investments  10 HOO {15 USD}; <== Here the cost is 15 USD, not 10 USD as in price directive
        

        original_posting_weight = convert.get_weight(original_posting)
        original_posting_weight_in_target_curr = convert_amount(original_posting_weight, target_currency, 
                                                                price_map, original_transaction.date)  
        
        
        # If the weight of the posting in the target currency is different from the posting units, converted to target 
        # currency this means, that the price used to weight the posting is different from the price in the price map, 
        # which will be used to convert the transaction to single currency.
        #
        # In this case we need to add a posting, which will correct the price difference
        # This posting will go to the account, which is used to record price differences
        if not (original_posting_weight_in_target_curr == new_units):
            assert original_posting_weight_in_target_curr.currency == new_units.currency, f"Internal logic error: original_posting_weight_in_target_curr.currency != new_units.currency"
            
            if original_posting.units.currency == target_currency:
                
                # Here looking at the situation like this, when converting to EUR
                """
                2024-01-01 price EUR 1.0 USD 

                2024-01-01 * "Openning balance "
                    Assets:US:Bank      1000 USD
                    Assets:EU:Bank      1000 EUR
                    Equity:Opening-Balances

                2024-01-02 price EUR 2 USD 

                2024-01-03 * "Exchange USD to EUR not the ECB rate"
                    Assets:EU:Bank  250 EUR @ 4 USD                   <==========
                    Assets:US:Bank -1000 USD
                """

                unreal_gains_meta_msg = f"Price difference compensation when converting {original_posting_weight.number} {original_posting_weight.currency} to {target_currency}. 'price' directive price is {new_units.number/original_posting.units.number}, price used to weight the posting is {original_posting_weight_in_target_curr.number/original_posting.units.number}"
                price_diff_acc = f"{account_for_price_diff}:{target_currency}-{original_posting_weight.currency}{GAINS_SUFFIX}"
                
            else:
                
                # Here looking at the situation like this, when converting to USD
                """
                2024-01-01 price EUR 1.0 USD 

                2024-01-01 * "Openning balance "
                    Assets:US:Bank      1000 USD
                    Assets:EU:Bank      1000 EUR
                    Equity:Opening-Balances

                2024-01-02 price EUR 2 USD 

                2024-01-03 * "Exchange USD to EUR not the ECB rate"
                    Assets:EU:Bank  250 EUR @ 4 USD                   <==========
                    Assets:US:Bank -1000 USD
                """
                
                unreal_gains_meta_msg = f"Price difference compensation when converting {original_posting.units} to {target_currency}. 'price' directive price is {new_units.number/original_posting.units.number}, price used to weight the posting is {original_posting_weight_in_target_curr.number/original_posting.units.number}"
                price_diff_acc = f"{account_for_price_diff}:{target_currency}-{original_posting.units.currency}{GAINS_SUFFIX}"
            
            
            tracked_at_cost_meta_msg = TRACKED_NOT_AT_COST_META_MSG
                        
            if original_posting.cost is not None:
                tracked_at_cost_meta_msg = TRACKED_AT_COST_META_MSG
                
            
            
            meta = {f"{SINGLE_CURENCY_CONVERTER_MSG_META}": unreal_gains_meta_msg,
                    TRACKED_AT_COST_META_NAME: tracked_at_cost_meta_msg,
                    UNREALIZED_GAINS_CAUSE_META_NAME: "price_diff",
                    UNREALIZED_GAINS_BAL_S_ACC_META_NAME: original_posting.account}
            
            price_correction_posting = data.Posting(account=price_diff_acc,
                                                    units=Amount((original_posting_weight_in_target_curr.number - new_units.number),target_currency),
                                                    cost=None,
                                                    price=None,
                                                    flag=original_posting.flag,
                                                    meta=meta)
            
            converted_transaction.postings.append(price_correction_posting)

    account_for_error_correction = f"{account_for_price_diff}:{target_currency}-{target_currency}"
    converted_transaction = add_balance_error_correction_posting_if_needed(converted_transaction, 
                                                                            options, 
                                                                            account_for_error_correction)

    return converted_transaction, unconvertable_commodities_to_return

       
# SORT_ORDER = {Open: -20, Balance: -10, Transaction:0, Price:2, Document: 3, Close: 4}

# The same sort order as in beancount SORT_ORDER = {Open: -2, Balance: -1, Document: 1, Close: 2}
# But the price is placed before the Transaction. This is purely to make sure that unrealized gains transactions are 
# placed after prices
SORT_ORDER = {Open: -20, Balance: -10, Price: -5, Transaction: -1, Document: 10, Close: 20}


def entry_sortkey_func(entry):
    """Sort-key for entries. Default beancount sorting except that articicially created entries are placed before 
    the original entries. This is not really needed but just to bring some structure.

    Args:
      entry: An entry instance.
    Returns:
      A tuple of (date, integer, integer), that forms the sort key for the
      entry.
    """
    
    # Setting the default lineno to a low number, so that entries without lineno 
    # (which are the one artificially created by this tool) are placed before the entries with lineno
    return (entry.date, SORT_ORDER.get(type(entry), 0), entry.meta.get("lineno", -10))


def get_needed_converted_entries(entries, price_map, 
                                 currency_introduction_map: CurrencyIntroductionMap,
                                 options, 
                                 target_currency: str,
                                 start_date: datetime.date, 
                                 end_date: datetime.date,
                                 account_for_price_diff: Account,
                                 unconvertable_commodities: Commodities) -> tuple[list[NamedTuple], Commodities]:
    
    """Converts needed entries to the target currency
    Exacly what rules are used to determine, how to convert each entry type is described in the document entries_conversion_rules.md
    
    Args:
        entries: A list of entries to convert.
        price_map: A dictionary mapping (currency, date) pairs to conversion rates.
        currency_introduction_map: A dictionary mapping currencies to the date of their introduction.
        options: A dict of options.
        target_currency: The currency to convert to.
        start_date: The start date of the conversion.
        end_date: The end date of the conversion.
        account_for_price_diff: The account, which will be used to record price differences
        unconvertable_commodities: A set of commodities, which are unconvertable
    """
    
    entries_to_return = []
    
    unconverable_commodities_total = unconvertable_commodities.copy()
    
    
    # creating price_map from entries parameter
    price_map = prices.build_price_map(entries)    
    
    date_of_last_processed_entry = datetime.date(1, 1, 1)
    
    num_of_entries = len(entries)
    
    date_being_processed = start_date
    
    # moving_price_map = None
    
    day_before_start_date = start_date-datetime.timedelta(days=1)
    
    for entry in entries:
        
        try:
            
            entry_to_return = None
            
            # TODO: @Ev2geny: Check if this is needed, but now leaving just in case
            entry = copy.copy(entry)
            
            entry_date = entry.date
            
            # Dropping all entries, which are after the end_date
            if entry_date > end_date:
                break
            
            # is_last_entry = i==num_of_entries-1
        
            # Just double chcking, that we received entries in correctr order
            assert entry_date >= date_of_last_processed_entry, f"Entry {entry} has date {entry_date}, which is before date of last processed entry {date_of_last_processed_entry}"
                
            # We are preserving all non-transaction entries, which are before or equal to start_date
            
            if isinstance(entry, Open):
                if entry.currencies:
                
                    new_meta = copy.deepcopy(entry.meta) if entry.meta else {}
                    new_meta[SINGLE_CURENCY_CONVERTER_MSG_META] = f"Converted from original Open entry by removing currencies {entry.currencies}"
                    
                    entry_to_return = data.Open(new_meta, entry.date, entry.account, None, None)
                else:
                    entry_to_return = entry
                    
            elif isinstance(entry, Close):
                entry_to_return = entry
                
            elif isinstance(entry, Commodity):
                entry_to_return = entry
                
            elif isinstance(entry, Transaction):
                if entry_date <= day_before_start_date:
                    continue
                else:
                    entry_to_return, unconvertable_commodities = convert_transaction_to_new_currency(entry,
                                                                                                    target_currency,
                                                                                                    price_map,
                                                                                                    currency_introduction_map,
                                                                                                    unconvertable_commodities=unconverable_commodities_total,
                                                                                                    account_for_price_diff=account_for_price_diff,
                                                                                                    options=options)
                    
                    unconverable_commodities_total = unconverable_commodities_total|unconvertable_commodities
                                       
            elif isinstance(entry, Balance):
                continue
                                 
            elif isinstance(entry, Pad):
                # TODO: @Ev2geny: double check if anything needs to be done with Pad entries
                continue
            
            elif isinstance(entry, Note):
                entry_to_return = entry
            
            elif isinstance(entry, Document):
                entry_to_return = entry
                
            elif isinstance(entry, Price):
                entry_to_return = entry
                
            elif isinstance(entry, Event):
                entry_to_return = entry
                
            elif isinstance(entry, Query):
                entry_to_return = entry
                
            elif isinstance(entry, Custom):
                entry_to_return = entry
            
            else:
                raise RuntimeError(f"Internal logic error: unknown entry type: {entry}")        
                    
            assert entry_to_return is not None, f"Internal error: entry_to_return is None for entry {entry}"
            
        except Exception  as error:
            error_message = f"""
                             Error occured while processing the entry\n {print_entries_to_string([entry])}
                             """
            error_message = textwrap.dedent(error_message)
            
            raise RuntimeError(f"{error_message}") from error
            
        entries_to_return.append(entry_to_return)

                    
    return entries_to_return, unconverable_commodities_total


# The PriceChangesMap is a data structure, which is used to store price changes 
# Example:
# defaultdict(<class 'list'>,
#             {datetime.date(2023, 1, 1): [[('USD', 'EUR'), Decimal('0.75')],
#                                          [('CAR', 'EUR'), Decimal('4500.00')]],
#              datetime.date(2023, 1, 5): [[('USD', 'EUR'), Decimal('0.5')]],
#              datetime.date(2023, 1, 6): [[('USD', 'EUR'), Decimal('0.4')]]})
#
# The key elements datetime.date(2023, 1, 6) are sorted

PriceChangesMap = defaultdict[datetime.date,
                                    list[tuple[tuple[Currency, Currency], Decimal]]
                                    ]


def get_price_changes_map_of_interest(price_map, target_currency: Currency, start_date: datetime.date,
                                      end_date: datetime.date) -> PriceChangesMap:
    """
    Returns a PriceChangesMap, sorted by date, which contains only price changes,
    which are in the target currency and  in the target date range

    Args:
        price_map (_type_): _description_
        target_currency (str): _description_
        start_date (datetime.date): _description_
        end_date (datetime.date): _description_

    Returns:
        PriceChangesMap: _description_
    """
    # pprint(price_map)
    
    # Converting price_map dictionary to a flat list of Price entries
    # This will be a list of the following elements: [price_pair:tuple, price_change:tuple] 
    # E.g. [('CAR', 'EUR'), (datetime.date(2022, 12, 31), Decimal('5000.00'))]

    price_changes_db = []
    for curr_pair, single_pair_price_changes_db in price_map.items():
        # we are interested only in prices, which are in the target currency
        if curr_pair[1] == target_currency: 
            for date_price in single_pair_price_changes_db:
                price_changes_db.append((curr_pair, date_price))
        
    # Soring price changes by date
    price_changes_db = sorted(price_changes_db, key=lambda x: x[1][0])
    
    # result = defaultdict(list)
    
    result = OrderedDict()
    
    for curr_pair, date_price in price_changes_db:
        if date_price[0] < start_date:
            continue
        
        if date_price[0] > end_date:
            break
        
        # This shall be equivalent of using defaultdict, which is not used here
        # for the benefits of OrderedDict
        if not result.get(date_price[0]):
            result[date_price[0]] = [] 

        result[date_price[0]].append([curr_pair, date_price[1]])

    return result


def get_unrealized_gains_transactions(net_worth_calculator: BeanSummator,
                                      price_map,
                                      options,
                                      target_currency: Currency,
                                      start_date: datetime.date,
                                      end_date: datetime.date,
                                      unconvertable_commodities: Commodities,
                                      unreal_gains_p_l_acc: Account,
                                      group_p_l_acc_tr: bool) -> list[Transaction]:
    
    """ Returns a list of transactions, which represent unrealized gains and losses for the period from start_date to end_date
    Args:
        net_worth_calculator: A NetWorthCalculator instance
        price_map: A dictionary mapping (currency, date) pairs to conversion rates.
        options: A dict of options.
        target_currency: The currency to convert to.
        start_date: The start date of the period
        end_date: The end date of the period
        unconvertable_commodities: A set of commodities, which are unconvertable
        unreal_gains_p_l_acc: The account, which will be used to record unrealized gains and losses
        group_p_l_acc_tr: A boolean, which indicates if the unrealized gains and losses per price change shall be grouped 
                        in a single P&L account
                        
    Returns:
        A list of transactions
    
    """

    logger.debug(f"'get_unrealized_gains_transactions' is called for the period {start_date} => {end_date}")

    price_changes_map: PriceChangesMap = get_price_changes_map_of_interest(price_map, target_currency, start_date,
                                                                           end_date)
    # pprint(price_changes_map)
    
    logger.debug(f"Price changes map:\n {pformat(price_changes_map)}")
    
    result = []
    
    for date, daily_price_changes in price_changes_map.items():
        for daily_price_change in daily_price_changes:
            
            # These are just a type hints, no functionality
            daily_price_change: tuple[tuple[Currency, Currency], Decimal]
            currency_targetCurrency_pair: tuple[Currency, Currency] 
            price: Decimal
            
            currency_targetCurrency_pair, price = daily_price_change
            
            if currency_targetCurrency_pair[0] in unconvertable_commodities:
                
                error_str =    f"""
                                Problem is detected in provided beancount ledger.
                                There is a price entry for the commodity {currency_targetCurrency_pair[0]} vs {target_currency} on the date {date},
                                This commodity has been detected as unconvertable to the commodity {target_currency} in the past.
                                Such situation is not allowed, as it would not allow to perform correct conversion of ledger to {target_currency}"""
                
                error_str = textwrap.dedent(error_str)
                
                raise UnconvertableCommBecomesConvertibleErr(error_str)
            
            # getting net worth at the start of the day, which is equivalent to the net worth at the end of the 
            # previous day
            net_worth_start_of_day_multicurr: InventoryAggregator = net_worth_calculator.sum_till_date(date-datetime.timedelta(days=1)).clean_empty()
            
            # Extracting net worth part, which is contributed by the changed currency
            net_worth_start_of_day_in_changed_curr: InventoryAggregator = net_worth_start_of_day_multicurr.get_currency_positions(currency_targetCurrency_pair[0])
            
            # Calculating net worth beginning of the day in the target currency with the exchange rate as it was before the price change
            # The exchange rate as it was before the price change is the exchange rate, the way it was on the previous day
            net_worth_start_of_day_in_target_curr_prev_rate: InventoryAggregator = net_worth_start_of_day_in_changed_curr.convert(target_currency, price_map, date-datetime.timedelta(days=1))
            logger.debug(f"net_worth_start_of_day_in_target_curr_prev_rate:\n{pformat(net_worth_start_of_day_in_target_curr_prev_rate)}")
            
            # Now calculating net worth in the target currency with the exchange rate on that date
            net_worth_start_of_day_target_curr_new_rate: InventoryAggregator = net_worth_start_of_day_in_changed_curr.convert(target_currency, price_map, date)
            logger.debug(f"net_worth_start_of_day_target_curr_new_rate:\n{pformat(net_worth_start_of_day_target_curr_new_rate)}")
            
            # getting difference between net worth beginning of the day in the target currency and the net worth beginning of the day in the target currency, 
            # but with the exchange rate as it was before the price change
            unrealized_gains_inv_agg: InventoryAggregator = net_worth_start_of_day_target_curr_new_rate - net_worth_start_of_day_in_target_curr_prev_rate
            unrealized_gains_inv_agg = unrealized_gains_inv_agg.clean_empty().get_sorted()
            
            if unrealized_gains_inv_agg.is_empty():
                logger.debug(f"No unrealized gains on the date {date}")
                continue
            
            old_price = get_price(price_map, currency_targetCurrency_pair, date-datetime.timedelta(days=1))[1]
            new_price = get_price(price_map, currency_targetCurrency_pair, date)[1]
            currency_changed = currency_targetCurrency_pair[0]
            
            unrealized_gains_transaction = create_unrealized_gains_transaction(unrealized_gains_inv_agg, 
                                                                               date,
                                                                               currency_changed=currency_changed,
                                                                               old_price=old_price,
                                                                               new_price=new_price,
                                                                               net_worth_on_date_multicurr=net_worth_start_of_day_multicurr,
                                                                               target_currency=target_currency,
                                                                               options=options,
                                                                               unreal_gains_p_l_acc=unreal_gains_p_l_acc,
                                                                               group_p_l_acc_tr = group_p_l_acc_tr)
            
            if unrealized_gains_transaction is not None:
                result.append(unrealized_gains_transaction)
                # printer.print_entry(unrealized_gains_transaction)
            
    return result


def pass_entries_through_file(entries, options: dict | None) -> tuple[list, list, dict]:
    """
    This function prints entries to a string and then reads them back as 
    entries, errors and options.
    In addition options responsible for naming of accounts are added to the file:
    - name_assets
    - name_liabilities
    - name_income
    - name_expenses
    - name_equity
    This allows to create a ledger also with not standard names of accounts 
    
    This seemingly unnecessary step is needed to make sure that we play safe, meaning that 
    we know, that well tested beancount engine has fully run, detected any errors and created all necessary options

    Args:
        entries (list): A list of entries
        options (dict): A dictionary of options

    Returns:
        entries, errors, options
    """
    # with tempfile.NamedTemporaryFile("a", delete_on_close=False, encoding="utf-8") as f:
    f = io.StringIO()
            
    if options:
        options_str = f"""
        option "name_assets" "{options["name_assets"]}"
        option "name_liabilities" "{options["name_liabilities"]}"
        option "name_income" "{options["name_income"]}"
        option "name_expenses" "{options["name_expenses"]}"
        option "name_equity" "{options["name_equity"]}"
        
        """
    options_str = textwrap.dedent(options_str)
    
    f.write(options_str)
    
    # f.write('option "inferred_tolerance_default" "EUR:0.0000000000000005"\n')
    printer.print_entries(entries, file=f)
    
    ledger_str = f.getvalue()
    
    entries, errors, options = loader.load_string(ledger_str)
    
    f.close()
    
    return entries, errors, options

@check_vs_beanquery
def get_equiv_sing_curr_entries(entries: list[NamedTuple],
                                options: dict,
                                /,
                                target_currency: Currency | None = None,
                                start_date: datetime.date | str | None = None,
                                end_date: datetime.date | str | None = None,
                                *,
                                unreal_gains_p_l_acc: Account = UNREAL_GAINES_P_AND_L_ACC,
                                self_testing_mode=False,
                                tolerance: str = TOLERANCE_DEF,
                                group_p_l_acc_tr=False,
                                shell_mode: bool = False,
                                debug_mode: bool = False) -> tuple[list[NamedTuple], list[NamedTuple], dict]:
    """
    Convert all ledger entries to a single target currency while calculating unrealized gains.

    Args:
    
    positional only arguments:
        entries (list[NamedTuple]): A list of Beancount ledger entries.
        
        options (dict): Beancount options.
    
    positional and keyword arguments:    
        target_currency (Currency, optional): The currency to convert all entries to. If not specified, the first
            operating currency in options is used.
        
        start_date (datetime.date | str | None, optional): The start date for conversion. If a string, it should be in
            'YYYY-MM-DD' format. If not specified, the date of the first entry is used.
        
        end_date (datetime.date | str | None, optional): The end date for conversion. If a string, it should be in
            'YYYY-MM-DD' format. If not specified, the date of the last entry is used.
        
    keyword only arguments:
        unreal_gains_p_l_acc (Account, optional): The account for unrealized gains. Defaults to
            UNREAL_GAINES_P_AND_L_ACC.
        
        self_testing_mode (bool, optional): If True, enables self-testing mode. Defaults to False. In self-testing mode,
            several checks are done using beanquery comparing the results on the converted and initial entries. This is
            primarily used for testing purposes but can also be enabled in production. Note: This is not used within the
            function but is used in the decorator `check_vs_beanquery`. Experiments show, that using this option increase 
            execution time by approximately 30%
        
        tolerance (str, optional): The tolerance used when performing verifications against the beanquery in self-testing
            mode. Defaults to "0.009". This should be a string convertible to a Decimal. Commas are stripped and ignored,
            as they are assumed to be thousands separators (the French comma separator as decimal is not supported). You
            may need to adjust this value depending on the size of your ledger, as the error can gradually build up if
            converting a large number of entries. Note: This is not used within the function but is used in the decorator
            `check_vs_beanquery`.
        
        group_p_l_acc_tr (bool, optional): If True, there will be only one posting to the P&L account in the unrealized
            gain transaction. Otherwise, there will be a P&L account posting for each balance sheet account which has
            unrealized gains. Defaults to False. Grouping the P&L account postings causes more compact unrealized gains
            transactions; such postings will not have the 'scc_bal_s_acc' meta.
        
        shell_mode (bool, optional): If True, the function knows that it is being called from the shell and will print
            some additional information to the console. Defaults to False.
            
        debug_mode (bool, optional): If True, debug logging is enabled. Defaults to False. Debug log is created in 
            the default temporary directory of the OS(e.g. on Windows c:\temp, on Linux /tmp). 

    Returns:
        tuple: A tuple containing:
            converted_entries (list[NamedTuple]): Converted entries.
            errors (list[NamedTuple]): Errors encountered during conversion.
            options (dict): Updated options.
    """

    if debug_mode:
        initilize_logging()

    # Making sure that we will not mess up with the original entries and options
    entries = copy.deepcopy(entries)
    options = copy.deepcopy(options)

    start_log_message = textwrap.dedent(f"""
        get_equiv_sing_curr_entries is called with the following parameters:
        
        Entries:
        {pformat(entries)}
        
        Options: 
        {pformat(options)}
        
        target_currency: {target_currency}
        start_date: {start_date}
        end_date: {end_date}
        unreal_gains_p_l_acc: {unreal_gains_p_l_acc}
        self_testing_mode: {self_testing_mode}
        """)
    
    logger.debug(start_log_message)

    if isinstance(start_date, str):
            start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            
    if isinstance(end_date, str):
        end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    
    # If start or end date is not specified, we are taking the first and the last date of the entries
    
    if not target_currency:
        if len(options["operating_currency"]) > 0:
            target_currency = options["operating_currency"][0]
        else:
            raise ValueError("'target_currency' is not specified and is not available in the operating currency option")
    
    logger.debug(f"Target currency: {target_currency}")
    
    if not start_date:
        start_date = entries[0].date
        
    if not end_date:
        end_date = entries[-1].date
    
    if start_date > end_date:
        raise ValueError(f"Start date ({start_date}) cannot be after the end date ({end_date})")
    
    if shell_mode:
        print(f"Attempting to convert entries to a single currency {target_currency} from {start_date} to {end_date}")
    
    entries_to_return = []
    
    # In unconverable_commodities we are storing all commodities, which are not convertible to the target currency
    # Once a commodity has been detected as being unconvertable, it shall meet certain conditions in order to allow 
    # conversion to the target currency:
    # -  It shall remain unconvertable for all entries afterwards. In practice this means, that there should not be a 
    #    price entry, which converts this commodity to the target currency at a later date
    #
    # -  There should not be any transactions, which convert this commodity to any other commodity. In another words,
    #    if UNC is unconvertable, there should not be any postings, which involve UNC and any other commodity, like:
    #    Assets:Bank  100 UNC @@ 100 EUR
    #    OR
    #    Assets:Bank  100 EUR @@ 100 UNC
    #    OR 
    #    Assets:Bank  100 UNC {100 EUR}
     
    unconvertable_commodities = set()
    
    price_map = prices.build_price_map(entries)
    
    # Dictionary, which maps currency to the date, when the currency was first used in any transaction in the ledger
    currency_introduction_map: CurrencyIntroductionMap = build_currency_introduction_map(entries)
  
    # Determining the regular expression, which will be used to filter accounts, which are used to calculate net worth
    # These are either Assets and Liabilities or renamed versions of them, which are specified in the options
    accounts_re = f"{options['name_assets']}|{options['name_liabilities']}"
  
    net_worth_calculator = BeanSummator(entries=entries, 
                                        options=options, 
                                        accounts_re=accounts_re)
  
    eqv_starting_transaction, eqv_starting_unconv_comm = create_equivalent_starting_transaction(net_worth_calculator,
                                                                                                options,
                                                                                                start_date,
                                                                                                target_currency,
                                                                                                price_map)
                                
    if eqv_starting_transaction:
        entries_to_return.append(eqv_starting_transaction)
        unconvertable_commodities = unconvertable_commodities | eqv_starting_unconv_comm
        
        logger.debug(f"Equivalent starting transaction:\n {printer.format_entry(eqv_starting_transaction)}")
        logger.debug(f"Unconvertable commodities: {unconvertable_commodities}")
    
    needed_eqv_entries, transaction_unconv_comm = get_needed_converted_entries(entries, 
                                                                               price_map,
                                                                               currency_introduction_map,
                                                                               options, 
                                                                               target_currency,
                                                                               start_date,
                                                                               end_date,
                                                                               account_for_price_diff = unreal_gains_p_l_acc,
                                                                               unconvertable_commodities = unconvertable_commodities)
    
    unconvertable_commodities = unconvertable_commodities | transaction_unconv_comm
    
    entries_to_return += needed_eqv_entries
    
    unrealized_gains_transactions = get_unrealized_gains_transactions(net_worth_calculator, 
                                                                      price_map, 
                                                                      options, 
                                                                      target_currency, 
                                                                      start_date, 
                                                                      end_date,
                                                                      unconvertable_commodities,
                                                                      unreal_gains_p_l_acc,
                                                                      group_p_l_acc_tr)
    # printer.print_entries(unrealized_gains_transactions)
    
    entries_to_return += unrealized_gains_transactions
    
    
    # sorting follwoing the beancount sorting rules before auto_insert_open
    entries_to_return = sorted(entries_to_return, key=data.entry_sortkey)
    
    # As we are adding new accounts, to play clean, we need to make sure, that all accounts have open entries
    # For this we are using the existing plugin auto_insert_open
    entries_to_return, _ = auto_insert_open(entries_to_return, {})
    
    # Sorting entries after auto_insert_open following our own stricter sorting rules (which still follow the beancount)
    entries_to_return = sorted(entries_to_return, key=entry_sortkey_func)
    
    entries_to_return, errors_to_return, options_to_return = pass_entries_through_file(entries_to_return, options)
    
    return entries_to_return, errors_to_return, options_to_return 


def parse_conf_string(args: str) -> tuple[list,dict]:
    """Parses a string, as positional and keyword arguments.
    It uses the same engine a Python uses to parse function arguments
    
    Used to parse optional configuration string, which is passed to the plugin by beancount
    
    args:
        conf_string (str): A string, which contains positional and keyword arguments
        
    returns:
        tuple: A tuple of two elements, where the first element is a list of positional arguments and the second 
        element is a dictionary of keyword arguments
    
    """
    # taken from here: https://stackoverflow.com/a/49723227/4432107
    args = 'f({})'.format(args)
    tree = ast.parse(args)
    funccall = tree.body[0].value

    args = [ast.literal_eval(arg) for arg in funccall.args]
    kwargs = {arg.arg: ast.literal_eval(arg.value) for arg in funccall.keywords}
    return args, kwargs



def get_equiv_sing_curr_entries_pulugin(entries, options, conf_string=None):
    """
    Allows to use the function get_equiv_sing_curr_entries as a beancount plugin by returning only 2 values, which 
    are needed for the plugin to work - entries and errors
    """
    
    logger.debug(f"get_equiv_sing_curr_entries_pulugin is called with the following entries")
    logger.debug(f"\n{print_entries_to_string(entries)}")
    
    args = []
    kwargs = {}
    
    if conf_string:
        try:
            args, kwargs = parse_conf_string(conf_string)
        except Exception as e:
            raise ValueError(f"Error while parsing configuration string, provided to plugin: '{conf_string}'") from e

    if len(args)>0:
        
        err_str = f""" 
        "Positional arguments are not supported as an input to plugin. 
        Provided positional arguments: {args}"
        
        You can specify in the configuration string any set of key word arguments, 
        which the function 'get_equiv_sing_curr_entries' can accept as a keyword argument.
        Refer to the function 'get_equiv_sing_curr_entries' docstring for more information.
        
        {get_equiv_sing_curr_entries.__doc__}
        """
        err_str = textwrap.dedent(err_str)
        
        raise ValueError("err_str")
    
    # entries_thr_file, errors_thr_file, options_thr_file = pass_entries_through_file(entries, options)
    
    # logger.debug(f"********** Entries, passed through the file ***************")
    # logger.debug('\n'+ print_entries_to_string(entries_thr_file))
    
    entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, **kwargs)
    return entries_eqv, errors_eqv


def main():
    
    class CustomHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
        """
        This class removes displaying destimation in the help message
        """
        def _get_default_metavar_for_optional(self, action):
            return ''

        # def _get_optional_metavar(self, action, default_metavar):
        #     return ''
        
    class CustomArgumentParser(argparse.ArgumentParser):
        def error(self, message):
            self.print_usage()
            self.exit(2, f'{self.prog}: error: {message}\n'
                        f'Run the program with -h or --help for more information.\n')
        
    # formatter_class = argparse.ArgumentDefaultsHelpFormatter
    formatter_class = CustomHelpFormatter
    
    parser = CustomArgumentParser(description="Attempts to convert all ledger entries to a single target currency, while calculating unrealized gains.",
                                  formatter_class=formatter_class)
    parser.add_argument('input_file_name', type=str, help='Input file name for conversion')
    parser.add_argument('output', type=str, 
                        help="""Output file name to created converted ledger. 
                                If '_bq_' is specifyed, then instead of writing to a file, the tool opens beanquery with the converted ledger""")
    parser.add_argument('-c', '--currency', type=str, dest='target_currency', help='Target currency to convert all entries to. If omitted, the first operating currency is used if available in the options. If not, an error is raised.')
    parser.add_argument('-s', '--start_date', type=str, dest='start_date', help='Optional start date for conversion in the format YYYY-MM-DD. If omitted, the date of the first entry is used')
    parser.add_argument('-e', '--end_date', type=str, dest='end_date', 
                        help='End date for conversion in the format YYYY-MM-DD. If omitted, the date of the last entry is used')
    parser.add_argument('-a', '--account', type=str, default=f'{UNREAL_GAINES_P_AND_L_ACC}', dest='unreal_gains_p_l_acc',
                        help='Account to book unrealized gains')
    parser.add_argument('-t', '--self_testing_mode', action='store_true', dest='self_testing_mode', 
                        help="""In the self-testing mode, several checks are done using beanquery comparing the results on the converted and initial entries.
                                This is primary used for testing purposes, but can also be enabled in production.""")
    parser.add_argument('-T', '--tolerance', type=str, default="0.001", help='Tolerance for self-testing mode')
    parser.add_argument('-g', '--group_p_l', action='store_true', dest='group_p_l_acc_tr', 
                        help=f"""If this argument is used, then there will be only one posting to P&L account in a single unrealized gain transaction.
                                 Otherwise (if this argument is not provided) there will be a P&L account posting for each Bal Sheet account, which has unrealized gains. 
                                 Usage of this argument causes more compact unrealized gains transactions, but such
                                 posting will not have the {UNREALIZED_GAINS_BAL_S_ACC_META_NAME} meta""")
    
    
    args = parser.parse_args()
    
    if args.start_date:
        args.start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d").date()
    if args.end_date:
        args.end_date = datetime.datetime.strptime(args.end_date, "%Y-%m-%d").date()
    
    entries, errors, options = loader.load_file(args.input_file_name)
    
    entries_eqv, errors_eqv, options_eqv = get_equiv_sing_curr_entries(entries, options, 
                                                                        target_currency =args.target_currency, 
                                                                        start_date = args.start_date, 
                                                                        end_date = args.end_date,
                                                                        unreal_gains_p_l_acc = args.unreal_gains_p_l_acc,
                                                                        self_testing_mode = args.self_testing_mode,
                                                                        tolerance=args.tolerance,
                                                                        group_p_l_acc_tr=args.group_p_l_acc_tr,
                                                                        shell_mode=True)
    if args.output == "_bq_":
        # Opening a temporary file to write the converted ledger
        with tempfile.NamedTemporaryFile("w", delete=True, encoding="utf-8", delete_on_close=False) as f:
            printer.print_entries(entries_eqv, file=f)
            f.close()
            os.system(f"python -m beanquery {f.name}")
            
    else:
        printer.print_entries(entries_eqv, file=open(args.output, "w", encoding="utf-8"))
        if len(errors_eqv)>0:
            print(f"File {args.output} has been created. Beancount has detected the following errors in the converted file")
            printer.print_errors(errors_eqv)
            
        else:
            print(f"File {args.output} has been successfully created")
   
def initilize_logging():
    """Initializes logging
    """
    log_file_dir = tempfile.gettempdir()
    
    logging.getLogger('beanpand.summator').setLevel(logging.INFO)
    root_logger = logging.getLogger()
    # Set this to logging.DEBUG to see all debug messages
    root_logger.setLevel(logging.DEBUG)
    # Adding file handler
    
    this_file_path = Path(__file__)
     
    
    file_for_logging = log_file_dir/Path(this_file_path.stem).with_suffix(".log")
    
    # file_for_logging.touch(exist_ok=True)
    
    file_handler = logging.FileHandler(file_for_logging, "a", encoding="utf-8")
    # Creating formatter, which displays time, level, module name, line number and message
    file_handler_formatter = logging.Formatter('%(levelname)s -%(name)s- %(module)s - %(lineno)d - %(funcName)s - %(message)s')
    
    # Adding formatter to file handler
    file_handler.setFormatter(file_handler_formatter)
    root_logger.addHandler(file_handler)
    logger = logging.getLogger(__name__)

    logger.debug("\n************** sing_curr_conv.main is called *******************")
            

if __name__ == "__main__":
    """Main function, which is called when the script is run from the command line
    It sets the logging and calls the main function
    """
    
    # initilize_logging()

    main()

        
         