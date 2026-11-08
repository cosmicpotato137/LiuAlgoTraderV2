"""Configuration, data access, shared types and utilities.

Modules
-------
assets
    Quote precision and minimum order size of tradable assets.
concurrency
    Determine how many consumer processes to run.
config
    Framework-wide configuration settings.
database
    Database connection pool and SQL results as pandas DataFrames.
exceptions
    Exceptions raised by the framework.
hyperparameter
    Hyper-parameter definitions for the back-test optimizer.
log
    Logging set-up for the framework's processes.
types
    Enumerations and broker-neutral data types shared by the framework.
websocket_listener
    Listen on a websocket-client connection from asynchronous code.
"""
