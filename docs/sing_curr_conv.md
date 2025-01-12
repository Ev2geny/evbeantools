<!-- <style>
H1{color:DarkBlue;}
H2{color:Blue;}
H3{color:Blue;}
H4{color:Blue;}
H5{color:Blue;}
</style> -->

# sing_curr_conv: Net Worth Change Explainer / Unrealized Gains Analyzer

The **sing_curr_conv** is a tool to be used with the [beancount](https://github.com/beancount/beancount), a software for
[plain text](https://plaintextaccounting.org/) double-entry bookkeeping. Its purpose is to explain the Net Worth difference between any two dates in a multi-currency/multi-commodity ledger. It does this by creating a converted or "equivalent" ledger, on which further analysis can be performed using standard [beanquery](https://github.com/beancount/beanquery) queries.

This documents, describes all the features of the **sing_curr_cong**.

The Jupyter notebook [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb) shows how these features are implemented in practice. 

The Jupyter notebook [sing_curr_conv_usage.ipynb](sing_curr_conv_usage.ipynb) has detailed example of how the **sing_curr_conv** can be used in practice.

**Table of Contents**

- [sing\_curr\_conv: Net Worth Change Explainer / Unrealized Gains Analyzer](#sing_curr_conv-net-worth-change-explainer--unrealized-gains-analyzer)
  - [Problem Statement](#problem-statement)
    - [Unrealized Gains](#unrealized-gains)
    - [Hidden Gains](#hidden-gains)
  - [How Does the Single Currency Converter (SCC) Solve This?](#how-does-the-single-currency-converter-scc-solve-this)
  - [Guarantees](#guarantees)
    - [Definitions](#definitions)
      - [Net Worth Report](#net-worth-report)
      - [Net Worth Change Report](#net-worth-change-report)
      - [Original and Converted (Equivalent) Ledger](#original-and-converted-equivalent-ledger)
    - [Guarantee 1. ledger\_eqv Is Equivalent for Net Worth Report](#guarantee-1-ledger_eqv-is-equivalent-for-net-worth-report)
    - [Guarantee 2. ledger\_eqv Explains Net Worth Change](#guarantee-2-ledger_eqv-explains-net-worth-change)
    - [Guarantee 3. Difference Only in Unrealized Gains](#guarantee-3-difference-only-in-unrealized-gains)
  - [How to Install](#how-to-install)
  - [How to Use](#how-to-use)
    - [From a Command Line](#from-a-command-line)
    - [As a Function in Python Code](#as-a-function-in-python-code)
    - [As a Plugin](#as-a-plugin)
  - [More Technical Details](#more-technical-details)
    - [Unconvertable Currencies. Ledger Convertibility Requirements](#unconvertable-currencies-ledger-convertibility-requirements)
      - [Requirement 1](#requirement-1)
      - [Requirement 2](#requirement-2)
      - [Reason for Convertibility Requirements](#reason-for-convertibility-requirements)
    - [Converting Only Part of the Ledger. The "start\_date" and "end\_date" Parameters](#converting-only-part-of-the-ledger-the-start_date-and-end_date-parameters)
    - [SCC\_ Metadata](#scc_-metadata)
  - [Appendixes](#appendixes)
    - [Appendix A. Converting Entries](#appendix-a-converting-entries)
      - [Equivalent Opening Balance Single Currency Transaction](#equivalent-opening-balance-single-currency-transaction)
      - [Unrealized Gains Transaction](#unrealized-gains-transaction)
      - [“Hidden Gain” Posting](#hidden-gain-posting)
      - [Balance and Pad entries](#balance-and-pad-entries)
  - [References](#references)

---

## Problem Statement

### Unrealized Gains

Consider the following simple Beancount ledger:

```beancount
2020-01-01 open Assets:House
2020-01-01 open Equity:Opening-Balances

2020-01-01 * "Opening balances"
  Assets:House             1 HOUSE
  Equity:Opening-Balances

2020-01-01 price HOUSE 100000 USD

2021-01-01 price HOUSE 120000 USD ; <== New house price one year later
```

We can see that between January 1, 2020, and January 1, 2021, the Net Worth in this ledger has increased by 20,000 USD, due to the change in the house's market price.  
Yet there is no  **beanquery** query that can explain _why_ it changed. This happens because the change is caused by a commodity price change, which leads to [unrealized gains](https://www.investopedia.com/ask/answers/04/021204.asp). Although it's easy to see the cause in this simple example, analyzing this in a more complex, real-world ledger (with multiple commodity transfers and changing exchange rates) is practically impossible.

### Hidden Gains

Now consider another example, closely related to unrealized gains but slightly different:

```beancount
2024-01-01 open Assets:Bank
2024-01-01 open Assets:Crypto
2024-01-01 open Equity:Opening-Balances

2024-01-01 * "Opening balances"
  Assets:Bank              20000 USD
  Equity:Opening-Balances

2024-01-01 price BTC  40000 USD

2024-01-02 * "Buying some BTC"
  Assets:Bank        -20000 USD
  Assets:Crypto           1 BTC @ 20000 USD ; <== Buying BTC at a price significantly lower than the market

2024-01-03 price BTC  40000 USD
```

Between January 1 and January 3, the net worth in this ledger changes from 20,000 USD to 40,000 USD, even though there is no recorded Income. This arises because the BTC was purchased at half its market price (which, by the way, raises questions about some potential shady financial operations).

Once again, there is no  **beanquery** query to explain this gain in an Income Statement-like report.

## How Does the Single Currency Converter (SCC) Solve This?

The **sing_curr_conv** utility converts the original ledger into a new ledger, where:

- All transactions are converted into a target currency using the exchange rate applicable on the date of each transaction.
- Additional postings are inserted to record **hidden gains**.
- For every price change, an "unrealized gains" transaction is inserted, reflecting the same increase in Assets and Liabilities as the price change. All unrealized gains transactions follow the double-entry accounting principle and balance to zero:
  - Some postings go to **Assets** and/or **Liabilities** account(s).
  - Other postings go to **Income:UnrealizedGains:\<Target Currency>:\<Changed Currency>** (the exact account name is configurable).

(See more information in [Appendix A](#appendix-a-converting-entries).)

After these modifications, it becomes straightforward to use **beanquery** to extract unrealized gains information, as well as perform **Net Worth Change Analysis**.

- See the Jupyter notebook [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb) for an illustrative explanation of how **sing_curr_conv** works.  
- See [sing_curr_conv_usage.ipynb](sing_curr_conv_usage.ipynb) for a detailed example of how **sing_curr_conv** can be used to analyze the [example.beancount](https://github.com/beancount/beancount/blob/master/examples/example.beancount?plain=1) file provided with Beancount.

## Guarantees

### Definitions

Before discussing guarantees, let us define a few terms.

#### Net Worth Report

let us define the  **Net Worth Report** expressed, if possible, in a single **reporting_currency**  for a certain date **nw_date**, broken down by accounts, using the following beanquery query:

```
SELECT account, convert(SUM(position),'{reporting_currency}',{nw_date}) as amount
WHERE
    date <= {nw_date}
    AND 
    account ~ 'Assets|Liabilities'
```

In other words, Net Worth is the combined balance of all **Assets** and **Liabilities** up to and including that date.

Note that, following accepted accounting practices \[[1](#gaap)\], **Assets** and **Liabilities** are translated into the reporting currency using the exchange rate in effect on the date of the Net Worth report. For instance, to determine the current value of your bitcoins, you need to know only your current bitcoin holdings and the current bitcoin price, not the various exchange rates at which you bought them in the past.

Let us assume, that the above query will be used by the function `net_worth` and in this case we can write this more formally in a form of a pseudo-code:

```
net_worth_report = net_worth(ledger, nw_date, reporting_currency)
```

#### Net Worth Change Report

Let us define the **Net Worth Change report** between a **start_date** and an **end_date**, expressed in a single **reporting_currency** and broken down by accounts, as the result of the following **beanquery** query:

```
SELECT account, SUM(convert(position, '{reporting_currency}', date)) as amount
WHERE
    account ~ 'Income|Expenses|Liabilities'
    AND
    date >= {start_date}
    AND
    date <= {end_date}
```

In other words, the **Net Worth Change report** captures all postings to **Income**, **Expenses**, and **Liabilities** over a certain period.

Again, inline with accepted accounting practices \[[1](#gaap)\], **Income**, **Expenses**, and **Liabilities** are translated into the reporting currency using the exchange rate in effect on the transaction date (in contrast to the Net Worth report, which uses the exchange rate on the report date).  
Thus, for example, if you purchased an item for 60 Turkish lira while on vacation in Turkey when 60 lira equaled 2 USD, it will remain 2 USD in the Net Worth Change report, regardless of subsequent exchange rate fluctuations.

Define this function to calculate the Net Worth Change report:

```
net_worth_change_report = net_worth_change(ledger, start_date, end_date, reporting_currency)
```

#### Original and Converted (Equivalent) Ledger

- **ledger_ori** denotes the original ledger.
- **ledger_eqv** denotes the equivalent (converted) ledger produced by running **sing_curr_conv** on the original ledger.

### Guarantee 1. ledger_eqv Is Equivalent for Net Worth Report

Running the **Net Worth** report on the original and equivalent ledgers produces identical results. Formally:

<pre><b>net_worth(<u>ledger_ori</u>, date_x, reporting_currency) == net_worth(<u>ledger_eqv</u>, date_x, reporting_currency)</b></pre>


### Guarantee 2. ledger_eqv Explains Net Worth Change

The **sing_curr_conv** creates a ledger that (unlike the original) can fully explain the change in **Net Worth** between any two dates by using the **Net Worth Change** report.

<pre><b>
   SUM( net_worth(ledger, <u>end_date</u>, reporting_currency) )
 - SUM( net_worth(ledger, <u>start_date</u>, reporting_currency) )
            ==
  -SUM( net_worth_change(ledger_eqv, <u>start_date</u> + 1, <u>end_date</u>, reporting_currency) )
</b></pre>

Notes:

1) We use **SUM()** because both **net_worth** and **net_worth_change** are defined to produce a report grouped by account, so **SUM(net_worth)** represents the total Net Worth as a single number (actually we may have several single numbers in case of [unconvertable currencies](#unconvertable-currencies-ledger-convertibility-requirements), this will be discussed later).  
2) **Net Worth** can be calculated either on the original ledger (**ledger_ori**) or on the equivalent ledger (**ledger_eqv**), thanks to the [Guarantee 1](#guarantee-1-ledger_eqv-is-equivalent-for-net-worth-report).  
3) Following the Plain Text Accounting (PTA) convention, **Income** is typically negative, and **Assets** are typically positive. Therefore, if the **Net Worth** increases, the **SUM(net_worth_change)** is negative.

### Guarantee 3. Difference Only in Unrealized Gains

The difference in the **Net Worth Change** reports, calculated on the original ledger versus the converted (equivalent) ledger, is exclusively due to unrealized gains.

<pre><b>
net_worth_change(<u>ledger_eqv</u>, ...) - net_worth_change(<u>ledger_ori</u>, ...) == unrealized_gains
</pre></b>

## How to Install

Install **sing_curr_conv** as part of the [evbeantools](../README.md) package.

## How to Use

There are three ways to use **sing_curr_conv**:

- From the command line
- As a function in Python code
- As a plugin

### From a Command Line

From the command line, **sing_curr_conv** can generate a converted ledger file or directly open the converted ledger in **beanquery**:

To run the **sing_curr_conv** from the command line and get a help type the following:

```
python -m evbeantools.sing_curr_conv -h
```

Example usage:

```
usage: sing_curr_conv.py [-h] [-c] [-s] [-e] [-a] [-t] [-T] [-g] input_file_name output

Attempts to convert all ledger entries to a single target currency, while calculating unrealized gains.     

positional arguments:
  input_file_name       Input file name for conversion
  output                Output file name to created converted ledger. If '_bq_' is specifyed, then instead  
                        of writing to a file, the tool opens beanquery with the converted ledger

options:
  -h, --help            show this help message and exit
  -c , --currency       Target currency to convert all entries to. If omitted, the first operating
                        currency is used if available in the options. If not, an error is raised.
                        (default: None)
  -s , --start_date     Optional start date for conversion in the format YYYY-MM-DD. If omitted, the date   
                        of the first entry is used (default: None)
  -e , --end_date       End date for conversion in the format YYYY-MM-DD. If omitted, the date of the last  
                        entry is used (default: None)
  -a , --account        Account to book unrealized gains (default: Income:Unrealized-Gains)
  -t, --self_testing_mode
                        In the self-testing mode, several checks are done using beanquery comparing the     
                        results on the converted and initial entries. This is primary used for testing      
                        purposes, but can also be enabled in production. (default: False)
  -T , --tolerance      Tolerance for self-testing mode (default: 0.001)
  -g, --group_p_l       If this argument is used, then there will be only one posting to P&L account in a   
                        single unrealized gain transaction. Otherwise (if this argument is not provided)    
                        there will be a P&L account posting for each Bal Sheet account, which has
                        unrealized gains. Usage of this argument causes more compact unrealized gains       
                        transactions, but such posting will not have the scc_bal_s_acc meta (default:       
                        False)
```

### As a Function in Python Code

To use the function in your code:

```python
from evbeantools.sing_curr_conv import get_equiv_sing_curr_entries
```

Its API:

```python
def get_equiv_sing_curr_entries(entries: list[NamedTuple],
                                options: dict,
                                /,
                                target_currency: Currency | None = None,
                                start_date: datetime.date | str | None = None,
                                end_date: datetime.date | str | None = None,
                                *,
                                unreal_gains_p_l_acc: Account = UNREAL_GAINES_P_AND_L_ACC,
                                self_testing_mode=False,
                                tolerance: str = "0.001",
                                group_p_l_acc_tr = False,
                                shell_mode: bool = False) -> tuple[list[NamedTuple], list[NamedTuple], dict]:
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
            function but is used in the decorator `check_vs_beanquery`.
        
        tolerance (str, optional): The tolerance used when performing verifications against the beanquery in self-testing
            mode. Defaults to "0.001". This should be a string convertible to a Decimal. Commas are stripped and ignored,
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

    Returns:
        tuple: A tuple containing:
            converted_entries (list[NamedTuple]): Converted entries.
            errors (list[NamedTuple]): Errors encountered during conversion.
            options (dict): Updated options.
    """
```

For examples, see [sing_curr_conv_usage.ipynb](sing_curr_conv_usage.ipynb) and [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb).

### As a Plugin

It is debatable Whether it is a good idea to use the **sing_curr_conv** as a plugin , since it makes substantial changes to the ledger (see more details in the [Appendix A](#appendix-a-converting-entries)). A "parallel investigation" approach, where the converted ledger is used alongside the original, may be more suitable. Nevertheless, plugin functionality is available.

To use the **sing_curr_conv** as a plugin add the following line to the Beancount ledger file:

```
plugin "evbeantools.sing_curr_conv" "optional configuration string"
```

The optional configuration string can include the same optional keyword arguments that function [get_equiv_sing_curr_entries](#as-a-function-in-python-code) accepts. Pass them as you would in Python code.

For example:

```
plugin "evbeantools.sing_curr_conv" "self_testing_mode=True, target_currency='EUR'"
```

## More Technical Details

### Unconvertable Currencies. Ledger Convertibility Requirements

Let is define that a currency **YYY** is considered unconvertable to a currency **XXX** on a certain date **DateX** if the **beancount** ledger lacks any price entry (either **XXX** to **YYY** or **YYY** to **XXX**) on or before the **DateX**.

For example, in the ledger below, EUR is unconvertable to USD before 2020-01-01, but becomes convertable on and after that date:

```
2020-01-01 price EUR 1 USD
```

To explain Net Worth differences between any two dates, not all commodities must be convertable to a target currency, but any unconvertable currency must meet two requirements:

#### Requirement 1

If a currency is unconvertable at the **start_date** of an analysis period, it must remain unconvertable until the **end_date**.

For instance, if we attempt to convert the following entire ledger to EUR, then this ledger is deemed convertable:

```
2020-01-01 open Assets:Bank:Checking1
2020-01-01 open Assets:Bank:Checking2
2020-01-01 open Equity:Opening-Balances

2020-01-01 price EUR 1 USD

2020-01-01 * "Opening Balances"
  Assets:Bank:Checking1  100 USD
  Assets:Bank:Checking2  100 GBP ; <= GBP is unconvertable to EUR but meets Requirement 1
  Equity:Opening-Balances

2020-02-01 price EUR 2 USD
```

However, this ledger is not convertable:

```
2020-01-01 open Assets:Bank:Checking1
2020-01-01 open Assets:Bank:Checking2
2020-01-01 open Equity:Opening-Balances

2020-01-01 price EUR 1 USD

2020-01-01 * "Opening Balances"
  Assets:Bank:Checking1  100 USD
  Assets:Bank:Checking2  100 GBP ; <= GBP is unconvertable to EUR here
  Equity:Opening-Balances

2020-02-01 price EUR 2   USD

2020-03-01 price EUR 1.5 GBP ; <= GBP becomes convertable after 2020-03-01
```

#### Requirement 2

There must not be any transfers to or from an unconvertable currency during the analysis period.

For example, the following also fails convertibility:

```
2020-01-01 open Assets:Bank:Checking1
2020-01-01 open Assets:Bank:Checking2
2020-01-01 open Equity:Opening-Balances

2020-01-01 price EUR 1 USD

2020-01-01 * "Opening Balances"
  Assets:Bank:Checking1  100 USD
  Assets:Bank:Checking2  100 GBP ; <= GBP is unconvertable to EUR
  Equity:Opening-Balances

2020-02-01 price EUR 2 USD

2020-03-01 * "Transferring GBP to USD"  <= Converting unconvertable GBP to USD
  Assets:Bank:Checking1    200 USD
  Assets:Bank:Checking2   -100 GBP @@ 200 USD
```

#### Reason for Convertibility Requirements

These requirements are not limitations of **sing_curr_conv** but rather logical constraints.

Consider [Requirement 1](#requirement-1). If a currency becomes convertable partway through a period, the [Net Worth Report](#net-worth-report) at an earlier date would include two currencies (EUR plus GBP), but a report at a later date would include only EUR (because GBP is now convertable to EUR). It becomes impossible to generate a **Net Worth Change** report that explains how we moved from the initial EUR+GBP to a final EUR-only balance. (See [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb) for practical details.)

**sing_curr_conv** throws an error with a detailed explanation if it finds that a ledger violates these requirements.

### Converting Only Part of the Ledger. The "start_date" and "end_date" Parameters

The **start_date** and **end_date** parameters allow you to convert only a specific time window of the ledger to a single currency, so you can focus on **Net Worth Change** / **Unrealized Gains** analysis for just that window.

This is particularly useful if the ledger fails the [convertibility requirements](#unconvertable-currencies-ledger-convertibility-requirements) over its entire timespan, but meets them over a smaller time range.

For example, the following ledger is not convertable to EUR over the entire period, but it _can_ be split into two convertable periods:

- From the beginning until 2020-03-01
- From 2020-03-02 until the end

```
2020-01-01 open Assets:Bank:Checking1
2020-01-01 open Assets:Bank:Checking2
2020-01-01 open Equity:Opening-Balances

2020-01-01 price EUR 1 USD

2020-01-01 * "Opening Balances"
  Assets:Bank:Checking1  100 USD
  Assets:Bank:Checking2  100 GBP ; <= GBP is unconvertable to EUR
  Equity:Opening-Balances

2020-02-01 price EUR 2   USD

2020-03-02 price EUR 1.5 GBP  ; <= GBP becomes convertable to EUR starting here

2020-04-01 price EUR 3   USD
```

Therefore, **Net Worth Change** analysis can be applied to these two partial periods separately, but not to the entire ledger at once.

Refer to [Appendix A](#appendix-a-converting-entries) for more details on how **start_date** and **end_date** are handled.

### SCC_ Metadata

**sing_curr_conv** enriches the converted entries with extra metadata to:

1. Provide an explanation for how a particular converted or new entry was generated.
2. Provide additional data for beanquery analysis.

Below is an overview of the metadata. For examples, see [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb) and [sing_curr_conv_usage.ipynb](sing_curr_conv_usage.ipynb).

| Metadata Name          | Applies To                                                                       | Possible Values                | Description                                                                                                                                                                                                             |
|------------------------|----------------------------------------------------------------------------------|--------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **scc_msg**            | Entries, postings                                                                | Free text                      | Free-text description of how this entry/transaction/posting was created or converted from the original. Primarily for informational purposes.                                                                           |
| **scc_at_cost**        | Unrealized-gains transaction postings to <br>**Income:Unrealized-Gains:XXX-YYY** | `at_cost` or `no_cost`         | Indicates whether the commodity position that caused the unrealized gain was tracked at cost.                                                                                                                           |
| **scc_unreal_g_cause** | Unrealized-gains transaction postings to <br>**Income:Unrealized-Gains:XXX-YYY** | `price_change` or `price_diff` | Specifies whether the unrealized gain was caused by a price change (as per a price entry) or by a [“hidden gain”](#hidden-gains).                                                                                       |
| **scc_bal_s_acc**      | Unrealized-gains transaction postings to <br>**Income:Unrealized-Gains:XXX-YYY** | The balance sheet account name | While the unrealized gains account (**Income:Unrealized-Gains:XXX-YYY**) encodes the commodity that caused the unrealized gain, this metadata holds the name of the balance sheet account that had the unrealized gain. |

## Appendixes

### Appendix A. Converting Entries

This appendix explains how **sing_curr_conv** converts each type of entry, depending on whether it falls before **start_date**, between **start_date** and **end_date**, or after **end_date**. (If **start_date** and **end_date** are not provided, **start_date** is the date of the earliest entry in the ledger, and **end_date** is the date of the latest entry.)

These design decisions aim to:

- Ensure that all [Guarantees](#guarantees) are satisfied.
- Preserve as much original information as possible.
- Provide additional details in metadata.

See [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb) for a practical illustration.

| Entry Type    | Before *start_date*                                                                                                                                | From *start_date* to *end_date*                                                                                                                                                                                                                                            | After *end_date* |
|---------------|----------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------|
| **open**      | Remove account currency                                                                                                                            | Remove account currency                                                                                                                                                                                                                                                    | Drop             |
| **close**     | No change                                                                                                                                          | No change                                                                                                                                                                                                                                                                  | Drop             |
| **commodity** | No change                                                                                                                                          | No change                                                                                                                                                                                                                                                                  | Drop             |
| **tnx**       | Accumulate all postings into the [equivalent opening balance single currency transaction](#equivalent-opening-balance-single-currency-transaction) | Leave postings in unconvertable currencies as is. Otherwise:<br> convert postings to the target currency<br> remove cost and price info<br> If necessary, add a “hidden gain” posting to the transaction<br> If needed, add "Small value Balance error correction posting" | Drop             |
| **balance**   | [Drop](#balance-and-pad-entries)                                                                                                                   | [Drop](#balance-and-pad-entries)                                                                                                                                                                                                                                           | Drop             |
| **pad**       | [Drop](#balance-and-pad-entries)                                                                                                                   | [Drop](#balance-and-pad-entries)                                                                                                                                                                                                                                           | Drop             |
| **note**      | No change                                                                                                                                          | No change                                                                                                                                                                                                                                                                  | Drop             |
| **document**  | No change                                                                                                                                          | No change                                                                                                                                                                                                                                                                  | Drop             |
| **price**     | No change                                                                                                                                          | No change. Create a corresponding [unrealized gains transaction](#unrealized-gains-transaction).                                                                                                                                                                           | Drop             |
| **event**     | No change                                                                                                                                          | No change                                                                                                                                                                                                                                                                  | Drop             |
| **query**     | No change                                                                                                                                          | No change                                                                                                                                                                                                                                                                  | Drop             |
| **custom**    | No change                                                                                                                                          | No change                                                                                                                                                                                                                                                                  | Drop             |

#### Equivalent Opening Balance Single Currency Transaction

When a **start_date** is specified and there are transactions on or before **start_date - 1**, an "equivalent opening balance" transaction is created with the date **start_date - 1**. This transaction aggregates the previous transactions (up to **start_date - 1**) converted to the target currency at the **start_date - 1** exchange rate. It reproduces the same [Net Worth Report](#net-worth-report) as the original ledger on **start_date - 1**, but with postings to balance sheet accounts offset by one or more postings to **Equity:OpeningBalances**.

The main purpose is to produce a **ledger_eqv** when the [convertibility requirements](#unconvertable-currencies-ledger-convertibility-requirements) are not met for the entire ledger but are met if part of the ledger is skipped. See the [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb) for an example.

#### Unrealized Gains Transaction

An unrealized gains transaction is inserted on every date where a price changes, which causes unrealized gain. It adds the appropriate amounts to balance sheet accounts (converted to the target currency) that reflect the price increase. Following double-entry principles, an offsetting amount is posted by default to the **Income:UnrealizedGains:\<Target Currency>:\<Changed Currency>**. The **scc_unreal_g_cause** metadata is set to the value `price_change`.

If needed, a **Small value Balance error correction posting** is added.

See [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb) for examples.

#### “Hidden Gain” Posting

A hidden gain posting is added if within a single transaction there was a transfer of funds from one commodity to another at an exchange rate, which is different from the price entry rate, applicable for this date (see the [Hidden Gains example](#hidden-gains)). This extra posting records the difference as an unrealized gain to the same unrealized gains account **Income:UnrealizedGains:\<Target Currency>:\<Changed Currency>**, however the **scc_unreal_g_cause** metadata is set to the value `price_diff`.

See [how_sing_curr_conv_works.ipynb](how_sing_curr_conv_works.ipynb) for examples.

#### Balance and Pad entries

Balance and Pad entries are totally dropped due to the following reasons:

- they would not provided any added value for the **sing_curr_conv** purposes, as errors detection and padding should have been done already in the original ledger
- Balance entry requires to specify a balance for a particular currency. However in the situation when there are several currencies in one account, this balance assertion will fail, if we convert all of them to a target currency 

## References
<a id="gaap"></a>[1] Generally Accepted Accounting Principles (GAAP), ASC 830, "Foreign Currency Matters"

<a id="reddit_gainstrack"></a>[2] [Reddit discussion about GainsTrack](https://www.reddit.com/r/plaintextaccounting/comments/19c1xv7/comment/kj65xs4/?utm_source=share&utm_medium=web3x&utm_name=web3xcss&utm_term=1&utm_content=share_button)
