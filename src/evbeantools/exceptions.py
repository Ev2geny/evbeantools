class BeanPandException(Exception):
    pass

class InputFileException(BeanPandException):
    pass

class WrongSplitTransaction(InputFileException):
    pass

