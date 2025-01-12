<!-- <style>
H1{color:DarkBlue;}
H2{color:Blue;}
H3{color:Blue;}
H4{color:Blue;}
H5{color:Blue;}
</style> -->

# evbeantools
A set of tools and plugins to be used with the [beancount](https://github.com/beancount/beancount), a tool for a Double-Entry Accounting from Text Files. 

**evbeantools** include, but are not limited to the tools to facilitate the usage of the beancount in,  the Jupyter notebook environment.

At the moment this is very much work in progress. Below are mentioned the components, which are considered to be mature enough (developed, documented, tested and covered by unit tests) to be presented to others.

**Table of Contents**

- [evbeantools](#evbeantools)
  - [Installation](#installation)
  - [Components](#components)
    - [sing\_curr\_conv: Neth Worth Change explainer / Unrealized Gains analyzer](#sing_curr_conv-neth-worth-change-explainer--unrealized-gains-analyzer)


## Installation

```
pip install git+https://github.com/Ev2geny/evbeantools.git
```

Notes:

- **evbeantools** require  **beancount** v3
  
- currently, installing **evbeantools** also installs some dependencies that are not strictly required by all modules. For example, **pandas** and **ipykernel** are not needed for the functionality of the **sing_curr_conv** module, but they are required to run its interactive Jupyter-based documentation. In the future, **evbeantools** may be split into a Jupyter-specific package and the rest, but for now they are all bundled together in one package.

For installation for development refer to the [CONTRIBUTING.md](docs/CONTRIBUTING.md)  

## Components

### sing_curr_conv: Neth Worth Change explainer / Unrealized Gains analyzer

This tool makes it possible to explain changes in the Net Worth between any two dates in a situation of multi-currency / multi-commodity ledger with changing exchange rates and transfers of funds from one commodity to another (both cost and not cost-based tracked). This is achieved by creating a converted / equivalent ledger, on which further analysis can be done using  [beanquery](https://github.com/beancount/beanquery).

The tool can be used 

* from a command line
* as a function in Python code
* as a plugin

See more information in the [**sing_curr_conv** documentation](docs/sing_curr_conv.md).