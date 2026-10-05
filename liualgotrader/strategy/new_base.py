
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.db.models.accounts import Account
from liualgotrader.db.models.algo_run import AlgoRun
from liualgotrader.db.models.keystore import KeyStore
from liualgotrader.trade.base import TraderAPI

# Replaces scanner
class Filter(object):
    def __init__(self, data_loader: DataLoader):
        pass

    def run():
        # Returns symbols to trade
        pass


class Strategy(object):
    def __init__(self):
        pass