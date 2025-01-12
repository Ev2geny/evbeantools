# Contributing to evbeantools

clone repository

```
git clone https://github.com/Ev2geny/beancount.git
```

install in development mode

```
cd evbeantools

python -m pip install -e .[dev]
```

Notes

- specifying the `[dev]` will install some extra dependencies, which are only needed to run tests

run tests

```
python -m pytest
```

to create a pull request, create it against the branch `develop`
