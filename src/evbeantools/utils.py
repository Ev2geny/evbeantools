"""
Miscellaneous utility functions
"""

from datetime import date
import io

from beancount.parser import printer

def check_convert_date(input_date: date | str) -> date:
    """
    function checks if input_date is a date object or str, which represents date in the format YYYY-MM-DD
    
    returns date object
    """
    if isinstance(input_date, date):
        return input_date
    elif isinstance(input_date, str):
        # converting str in a format YYYY-MM-DD to date object
        return date.fromisoformat(input_date)
    else:
        raise ValueError(f"input_date shall be either date object or string in a format YYYY-MM-DD.\n"
                         f"The following was provided:\ninput_date = {input_date}, type = {type(input_date)}")


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


def print_errors_to_string(errors) -> str:
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


if __name__ == "__main__":
    # res = check_convert_date(date(2021,1,1))
    # print(res)
    # print(type(res))
    pass